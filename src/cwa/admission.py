"""Admission: each raw candidate is admitted as an Item or excluded with exactly one reason.

When a candidate fails several checks, the recorded reason is the earliest applicable code in
contract/reasons.json order (R-21).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jsonschema import ValidationError

from .contract import POLICY_FIELDS, REASONS, SLOT_DEFAULTS, validator
from .model import Item, ProducerIdentity
from .snapshot import Snapshot, usable_id

_PRECEDENCE = {code: rank for rank, code in enumerate(REASONS)}


def _rank(code: str) -> tuple[int, str]:
    # Ties (several missing fields) break alphabetically, which every language reproduces.
    return (_PRECEDENCE["missing_field:<name>" if code.startswith("missing_field:") else code], code)


@dataclass(frozen=True, slots=True)
class Exclusion:
    producer: str
    item_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Admission:
    items: tuple[Item, ...]
    excluded: tuple[Exclusion, ...]
    """Assembler-stage exclusions, ordered by producer id and then recorded item id."""
    defaults_filled: tuple[tuple[str, str], ...]
    """(item id, field) for every schema-valid candidate whose policy fields were filled (R-3, R-22)."""


def _schema_codes(error: ValidationError) -> list[str]:
    if error.validator == "required":
        return [f"missing_field:{name}" for name in error.validator_value if name not in error.instance]
    if error.validator == "enum" and list(error.absolute_path) == ["slot"]:
        return ["unknown_slot"]
    if error.validator == "enum" and list(error.absolute_path) == ["authority"]:
        return ["unknown_authority"]
    return ["invalid_structure"]


def _structure(candidate: Mapping[str, Any]) -> str | None:
    codes = [code for error in validator("context_item").iter_errors(candidate) for code in _schema_codes(error)]
    return min(codes, key=_rank) if codes else None


@dataclass(frozen=True, slots=True)
class _Context:
    snapshot: Snapshot
    producer: ProducerIdentity
    granted: Mapping[str, Any]
    """The route policy's entry for this producer."""
    id_uses: Counter[str]
    """How often each id appears across all candidates and producer exclusions."""


def _duplicate(item: Item, ctx: _Context) -> str | None:
    return "duplicate_item_id" if ctx.id_uses[item.id] > 1 else None


def _slot_permission(item: Item, ctx: _Context) -> str | None:
    # State is application-written (R-8): only state producers, whatever else a route lists.
    if item.slot not in ctx.granted["slots"] or (item.slot.startswith("state.") and ctx.producer.kind != "state"):
        return "producer_slot_not_allowed"
    return None


def _authority(item: Item, ctx: _Context) -> str | None:
    # R-1: the slot's role, or untrusted outside governance and knowledge. Prior model turns in
    # history are generated content and must be untrusted.
    role = SLOT_DEFAULTS[item.slot]["authority"]
    lowered = item.authority == "untrusted" and not item.slot.startswith("governance.") and item.slot != "evidence.knowledge"
    if item.authority != role and not lowered:
        return "authority_not_allowed"
    if item.slot == "interaction.history" and item.lineage == "generated" and item.authority != "untrusted":
        return "authority_not_allowed"
    return None


def _capability(item: Item, ctx: _Context) -> str | None:
    # R-15: permission comes from the authenticated capability policy's grant, never from item fields.
    if item.slot != "governance.capabilities":
        return None
    grant = ctx.snapshot.capabilities
    if (grant is None or ctx.producer.kind != "capability_policy" or ctx.producer.id != grant.policy_producer
            or item.id not in grant.allowed_ids):
        return "capability_not_allowed"
    return None


# Checks for schema-valid items from authenticated producers, in reasons.json order.
_CHECKS: tuple[Callable[[Item, _Context], str | None], ...] = (_duplicate, _slot_permission, _authority, _capability)


def _item_reason(item: Item, ctx: _Context) -> str | None:
    return next((reason for check in _CHECKS if (reason := check(item, ctx))), None)


def admit(snapshot: Snapshot) -> Admission:
    items, excluded, filled = [], [], []
    id_uses = Counter(
        [i for b in snapshot.batches for c in b.candidates if (i := usable_id(c))]
        + [row.item_id for b in snapshot.batches for row in b.excluded]
    )
    for batch in snapshot.batches:
        granted = snapshot.route_policy.document["producers"].get(batch.producer.id)
        authenticated = granted is not None and granted["kind"] == batch.producer.kind
        unnamed = 0
        for candidate in batch.candidates:
            item_id = usable_id(candidate)
            if item_id is None:
                item_id, unnamed = f"{batch.producer.id}#invalid-{unnamed}", unnamed + 1
            if not authenticated:
                excluded.append(Exclusion(batch.producer.id, item_id, "producer_not_authenticated"))
                continue
            if reason := _structure(candidate):
                excluded.append(Exclusion(batch.producer.id, item_id, reason))
                continue
            item = Item.from_json(candidate)
            filled += [(item.id, field) for field in item.defaults_filled]
            if reason := _item_reason(item, _Context(snapshot, batch.producer, granted, id_uses)):
                excluded.append(Exclusion(batch.producer.id, item_id, reason))
                continue
            items.append(item)
    return Admission(
        items=tuple(items),
        excluded=tuple(sorted(excluded, key=lambda e: (e.producer, e.item_id))),
        defaults_filled=tuple(sorted(filled, key=lambda f: (f[0], POLICY_FIELDS.index(f[1])))),
    )
