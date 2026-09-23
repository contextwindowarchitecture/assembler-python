"""Admission: each raw candidate is admitted as an Item or excluded with exactly one reason.

When a candidate fails several checks, the recorded reason is the earliest applicable code in
contract/reasons.json order (R-21).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import ValidationError

from .contract import POLICY_FIELDS, REASONS, validator
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


def _slot_permission(item: Item, producer: ProducerIdentity, granted: Mapping[str, Any]) -> str | None:
    # State is application-written (R-8): only state producers, whatever else a route lists.
    if item.slot not in granted["slots"] or (item.slot.startswith("state.") and producer.kind != "state"):
        return "producer_slot_not_allowed"
    return None


def _item_reason(item: Item, producer: ProducerIdentity, granted: Mapping[str, Any]) -> str | None:
    """The first failing check for a schema-valid item, in reasons.json order."""
    for check in (_slot_permission,):
        if reason := check(item, producer, granted):
            return reason
    return None


def admit(snapshot: Snapshot) -> Admission:
    items, excluded, filled = [], [], []
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
            if reason := _item_reason(item, batch.producer, granted):
                excluded.append(Exclusion(batch.producer.id, item_id, reason))
                continue
            items.append(item)
    return Admission(
        items=tuple(items),
        excluded=tuple(sorted(excluded, key=lambda e: (e.producer, e.item_id))),
        defaults_filled=tuple(sorted(filled, key=lambda f: (f[0], POLICY_FIELDS.index(f[1])))),
    )
