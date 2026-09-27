"""The immutable assembly input. Everything that can change the payload is in here (R-23)."""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from . import contract
from .canonical import canonical_json, digest
from .model import (Budget, CapabilityGrant, ConflictGroup, Placement, ProducerBatch, ProducerExclusion, ProducerIdentity,
                    Profile, RoutePolicy)
from .render import REGISTRY as RENDERERS, Renderer
from .strings import blank, utf16
from .tokenize import REGISTRY as TOKENIZERS, Tokenizer


class SnapshotError(ValueError):
    """The snapshot cannot be assembled at all. Raised before assembly, never mid-assembly."""

    def __init__(self, problems: list[str]):
        super().__init__("invalid snapshot:\n  " + "\n  ".join(problems))
        self.problems = problems


def usable_id(candidate: Mapping[str, Any]) -> str | None:
    """The candidate's id if it is a non-blank string (R-2)."""
    value = candidate.get("id")
    return value if isinstance(value, str) and not blank(value) else None


def _in_double_range(value: int) -> bool:
    try:
        float(value)
    except OverflowError:
        return False
    return True


def _not_i_json(value: Any, path: str = "") -> list[str]:
    """Paths of strings, keys included, holding a surrogate, and of numbers a double cannot hold (I-JSON, RFC 7493).
    After a JSON round trip every pair is one character, so any surrogate left is unpaired; JSON reads 1e400 as
    Infinity. RFC 8785 can serialize neither, so the snapshot has no digest (R-17)."""
    if isinstance(value, str):
        return [f"{path or '/'} holds an unpaired surrogate"] if any("\ud800" <= c <= "\udfff" for c in value) else []
    if isinstance(value, float) and not math.isfinite(value) or type(value) is int and not _in_double_range(value):
        return [f"{path or '/'} is not a number a double can hold"]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _not_i_json(v, f"{path}/{i}")]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _not_i_json(k, path) + _not_i_json(v, f"{path}/{k}")]
    return []


def _as_doubles(value: Any) -> Any:
    """Every number as the nearest IEEE 754 double, as JavaScript reads it (R-2; conformance/README.md, Numbers).
    Python keeps integers exact, so an integer beyond 2^53 becomes the double it rounds to, and every comparison then
    agrees with the other languages and with the digest, which already serializes numbers as doubles."""
    if type(value) is int and abs(value) > 2**53:
        return float(value)
    if isinstance(value, list):
        return [_as_doubles(v) for v in value]
    if isinstance(value, dict):
        return {k: _as_doubles(v) for k, v in value.items()}
    return value


def _item_order(item: Any) -> tuple[int, bytes, bytes]:
    """Items with a usable id by id, then by content; the rest after them, in their supplied order."""
    item_id = usable_id(item)
    return (0, utf16(item_id), canonical_json(item)) if item_id else (1, b"", b"")


def _normalize(document: dict[str, Any]) -> dict[str, Any]:
    """Canonical order, so producers returning in any order yield the same snapshot and payload.

    Items with a usable id sort by id, and candidates sharing an id by their canonical JSON. Items
    without one keep their supplied relative order after them, which keeps their
    {producer}#invalid-{n} trace ids stable across replays.
    """
    for batch in document["batches"]:
        batch["items"].sort(key=_item_order)
        batch["excluded"].sort(key=lambda row: (utf16(row["item_id"]), canonical_json(row)))
    document["batches"].sort(key=lambda batch: utf16(batch["producer"]["id"]))
    document["conflicts"].sort(key=lambda group: utf16(group["id"]))
    for group in document["conflicts"]:
        group["items"].sort(key=utf16)
    return document


def _conflict_errors(document: Mapping[str, Any]) -> list[str]:
    """Cross-references the schema cannot express (R-11): unique group ids, known item ids, no
    item in two groups, and fact keys the route policy defines."""
    problems = []
    known = {usable_id(item) for batch in document["batches"] for item in batch["items"]} | {
        row["item_id"] for batch in document["batches"] for row in batch["excluded"]}
    ids = [group["id"] for group in document["conflicts"]]
    if repeated := sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"conflict group ids repeat: {', '.join(repeated)}")
    owner: dict[str, str] = {}
    facts = document["route_policy"].get("facts", {})
    for group in document["conflicts"]:
        for item_id in group["items"]:
            if item_id not in known:
                problems.append(f"conflict group {group['id']} names {item_id!r}, which is not a candidate or producer exclusion")
            elif item_id in owner:
                problems.append(f"{item_id!r} belongs to more than one conflict group: {owner[item_id]}, {group['id']}")
            owner.setdefault(item_id, group["id"])
        if group["kind"] == "fact" and group["fact"] not in facts:
            problems.append(f"conflict group {group['id']} names fact {group['fact']!r}, which the route policy does not define")
    return problems


def _report_errors(document: Mapping[str, Any]) -> list[str]:
    """R-13, R-9: a near-duplicate or a superseded item a producer reports names a candidate it kept, from its own batch."""
    problems = []
    for batch in document["batches"]:
        candidates = {usable_id(item) for item in batch["items"]}
        for row in batch["excluded"]:
            for field in ("duplicate_of", "superseded_by"):
                if field in row and row[field] not in candidates:
                    problems.append(f"{row['item_id']} names {row[field]!r} as kept, which is not a candidate in {batch['producer']['id']}'s batch")
    return problems


def _profile_errors(profile: Profile, policy: Mapping[str, Any]) -> list[str]:
    """R-20: the profile names the route policy it was built for and places the slots every
    assembly on that route needs."""
    problems = []
    if profile.route != policy["route"]:
        problems.append(f"profile is for route {profile.route!r}, the route policy for {policy['route']!r}")
    if profile.route_policy_version != policy["version"]:
        problems.append(f"profile expects route policy {profile.route_policy_version!r}, snapshot has {policy['version']!r}")
    placed = {placement.slot for placement in profile.placement}
    for slot in ("governance.instructions", "interaction.query"):
        if slot not in placed:
            problems.append(f"profile does not place {slot}")
    if policy.get("parser", False) and "governance.output_contract" not in placed:
        problems.append("profile does not place governance.output_contract, which the parser route requires")
    return problems


@dataclass(frozen=True)
class Snapshot:
    assembly_time: str
    scope: Mapping[str, str]
    budget: Budget
    profile: Profile
    route_policy: RoutePolicy
    tokenizer: Tokenizer
    renderer: Renderer
    batches: tuple[ProducerBatch, ...]
    capabilities: CapabilityGrant | None
    conflicts: tuple[ConflictGroup, ...]
    _document: Mapping[str, Any]

    @classmethod
    def from_json(cls, document: Mapping[str, Any], *, tokenizers: Mapping[str, Tokenizer] = {},
                  renderers: Mapping[str, Renderer] = RENDERERS) -> Snapshot:
        """Validate a snapshot.schema.json document and freeze it. The caller's object is copied, never kept.

        tokenizers adds the caller's tokenizers, by id, to the built-in ones for this call only. A built-in id
        cannot be redefined, since conformance/README.md fixes what it counts."""
        if redefined := sorted(set(tokenizers) & set(TOKENIZERS)):
            raise ValueError(f"tokenizer {', '.join(redefined)} is built in; give yours another id")
        tokenizers = {**TOKENIZERS, **tokenizers}
        data: dict[str, Any] = json.loads(json.dumps(document))
        if problems := contract.errors("snapshot", data) + _not_i_json(data):
            raise SnapshotError(problems)
        data = _normalize(_as_doubles(data))

        problems = []
        tokenizer, renderer = tokenizers.get(data["tokenizer"]), renderers.get(data["renderer"])
        if tokenizer is None:
            problems.append(f"unknown tokenizer {data['tokenizer']!r}")
        if renderer is None:
            problems.append(f"unknown renderer {data['renderer']!r}")
        p = data["profile"]
        profile = Profile(p["spec"], p["id"], p["version"], p["route"], p["model_family"], p["route_policy_version"],
                          tuple(Placement(e["slot"], e["wrap"]) for e in p["placement"]), copy.deepcopy(p["evaluation"]))
        if renderer is not None:
            problems += renderer.profile_errors(profile)
        policy = data["route_policy"]
        problems += _profile_errors(profile, policy)
        producer_ids = [b["producer"]["id"] for b in data["batches"]]
        if duplicates := sorted({i for i in producer_ids if producer_ids.count(i) > 1}):
            problems.append(f"producer ids appear in more than one batch: {', '.join(duplicates)}")
        problems += _conflict_errors(data) + _report_errors(data)
        if problems:
            raise SnapshotError(problems)
        assert tokenizer is not None and renderer is not None  # an unknown one is a problem above

        grant = data.get("capabilities")
        return cls(
            assembly_time=data["assembly_time"],
            scope=dict(data["scope"]),
            budget=Budget(**data["budget"]),
            profile=profile,
            route_policy=RoutePolicy(policy["route"], policy["version"], copy.deepcopy(policy)),
            tokenizer=tokenizer,
            renderer=renderer,
            batches=tuple(
                ProducerBatch(
                    producer=ProducerIdentity(b["producer"]["id"], b["producer"]["kind"]),
                    candidates=tuple(b["items"]),
                    excluded=tuple(ProducerExclusion(**row) for row in b["excluded"]),
                )
                for b in data["batches"]
            ),
            capabilities=CapabilityGrant(grant["policy_producer"], grant["allow_list_version"], tuple(grant["allowed_ids"])) if grant else None,
            conflicts=tuple(ConflictGroup(g["id"], g["kind"], tuple(g["items"]), g.get("fact")) for g in data["conflicts"]),
            _document=data,
        )

    @classmethod
    def freeze(cls, *, tokenizers: Mapping[str, Tokenizer] = {}, renderers: Mapping[str, Renderer] = RENDERERS,
               **fields: Any) -> Snapshot:
        """Keyword form of from_json; field names and values follow snapshot.schema.json."""
        return cls.from_json(fields, tokenizers=tokenizers, renderers=renderers)

    def to_json(self) -> dict[str, Any]:
        """The normalized snapshot document, suitable for storing and replaying."""
        return copy.deepcopy(dict(self._document))

    def digest(self) -> str:
        """SHA-256 of the RFC 8785 serialization of to_json(): the replay key."""
        return digest(self._document)
