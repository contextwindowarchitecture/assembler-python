"""The immutable assembly input. Everything that can change the payload is in here (R-23)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping

from . import contract
from .canonical import canonical_json, digest, utf16
from .model import (Budget, CapabilityGrant, ConflictGroup, Placement, ProducerBatch, ProducerExclusion, ProducerIdentity,
                    Profile, RoutePolicy)
from .render import REGISTRY as RENDERERS, Renderer
from .tokenize import REGISTRY as TOKENIZERS, Tokenizer


class SnapshotError(ValueError):
    """The snapshot cannot be assembled at all. Raised before assembly, never mid-assembly."""

    def __init__(self, problems: list[str]):
        super().__init__("invalid snapshot:\n  " + "\n  ".join(problems))
        self.problems = problems


def usable_id(candidate: Mapping[str, Any]) -> str | None:
    """The candidate's id if it is a non-blank string (R-2)."""
    value = candidate.get("id")
    return value if isinstance(value, str) and value.strip() else None


def _normalize(document: dict[str, Any]) -> dict[str, Any]:
    """Canonical order, so producers returning in any order yield the same snapshot and payload.

    Items with a usable id sort by id, and candidates sharing an id by their canonical JSON. Items
    without one keep their supplied relative order after them, which keeps their
    {producer}#invalid-{n} trace ids stable across replays.
    """
    for batch in document["batches"]:
        batch["items"].sort(key=lambda item: (0, utf16(usable_id(item)), canonical_json(item)) if usable_id(item) else (1, b"", b""))
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
    def from_json(cls, document: Mapping[str, Any], *, tokenizers: Mapping[str, Tokenizer] = TOKENIZERS,
                  renderers: Mapping[str, Renderer] = RENDERERS) -> Snapshot:
        """Validate a snapshot.schema.json document and freeze it. The caller's object is copied, never kept."""
        document = json.loads(json.dumps(document))
        if problems := contract.errors("snapshot", document):
            raise SnapshotError(problems)
        document = _normalize(document)

        problems = []
        tokenizer, renderer = tokenizers.get(document["tokenizer"]), renderers.get(document["renderer"])
        if tokenizer is None:
            problems.append(f"unknown tokenizer {document['tokenizer']!r}")
        if renderer is None:
            problems.append(f"unknown renderer {document['renderer']!r}")
        p = document["profile"]
        profile = Profile(p["id"], p["version"], p["route"], p["model_family"], p["route_policy_version"],
                          tuple(Placement(e["slot"], e["wrap"]) for e in p["placement"]), copy.deepcopy(p["evaluation"]))
        if renderer is not None:
            problems += renderer.profile_errors(profile)
        policy = document["route_policy"]
        problems += _profile_errors(profile, policy)
        producer_ids = [b["producer"]["id"] for b in document["batches"]]
        if duplicates := sorted({i for i in producer_ids if producer_ids.count(i) > 1}):
            problems.append(f"producer ids appear in more than one batch: {', '.join(duplicates)}")
        problems += _conflict_errors(document)
        if problems:
            raise SnapshotError(problems)

        grant = document.get("capabilities")
        return cls(
            assembly_time=document["assembly_time"],
            scope=dict(document["scope"]),
            budget=Budget(**document["budget"]),
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
                for b in document["batches"]
            ),
            capabilities=CapabilityGrant(grant["policy_producer"], grant["allow_list_version"], tuple(grant["allowed_ids"])) if grant else None,
            conflicts=tuple(ConflictGroup(g["id"], g["kind"], tuple(g["items"]), g.get("fact")) for g in document["conflicts"]),
            _document=document,
        )

    @classmethod
    def freeze(cls, **fields: Any) -> Snapshot:
        """Keyword form of from_json; field names and values follow snapshot.schema.json."""
        return cls.from_json(fields)

    def to_json(self) -> dict[str, Any]:
        """The normalized snapshot document, suitable for storing and replaying."""
        return copy.deepcopy(dict(self._document))

    def digest(self) -> str:
        """SHA-256 of the RFC 8785 serialization of to_json(): the replay key."""
        return digest(self._document)
