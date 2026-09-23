"""Immutable values an assembly reads. Built only from a schema-validated snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .contract import POLICY_FIELDS, SLOT_DEFAULTS


def _frozen(mapping: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True, slots=True)
class Budget:
    input: int
    reserved_output: int


@dataclass(frozen=True, slots=True)
class Variant:
    id: str
    body: str
    method: str
    lineage: str


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    slot: str
    source: str
    source_version: str
    authority: str
    trust: str
    freshness: str
    body: str
    token_budget: int | None
    variants: tuple[Variant, ...]
    conflict_policy: str
    lineage: str
    eligibility: str
    injection_risk: str
    expires: str | None = None
    scope: Mapping[str, str] = _frozen(None)
    relevance: float | None = None
    tier: str | None = None
    revoked_by: str | None = None
    defaults_filled: tuple[str, ...] = ()
    """Policy fields the producer omitted and the slot defaults supplied (R-3)."""

    @classmethod
    def from_json(cls, data: Mapping[str, Any], overrides: Mapping[str, Any] | None = None) -> Item:
        """Build from a schema-valid item; omitted policy fields come from the slot defaults as
        replaced by the route's overrides for that slot (R-3)."""
        defaults = {**SLOT_DEFAULTS[data["slot"]], **(overrides or {})}
        filled = tuple(field for field in POLICY_FIELDS if field not in data)
        merged = {**{field: defaults[field] for field in filled}, **data}
        return cls(
            id=merged["id"], slot=merged["slot"], source=merged["source"], source_version=merged["source_version"],
            authority=merged["authority"], trust=merged["trust"], freshness=merged["freshness"], body=merged["body"],
            token_budget=merged["token_budget"], variants=tuple(Variant(**v) for v in merged["variants"]),
            conflict_policy=merged["conflict_policy"], lineage=merged["lineage"], eligibility=merged["eligibility"],
            injection_risk=merged["injection_risk"], expires=merged.get("expires"), scope=_frozen(merged.get("scope")),
            relevance=merged.get("relevance"), tier=merged.get("tier"), revoked_by=merged.get("revoked_by"),
            defaults_filled=filled,
        )


@dataclass(frozen=True, slots=True)
class ProducerIdentity:
    """Who the application authenticated for a batch. Never read from item fields (R-15)."""
    id: str
    kind: str


@dataclass(frozen=True, slots=True)
class ProducerExclusion:
    item_id: str
    reason: str
    stage: str


@dataclass(frozen=True, slots=True)
class ProducerBatch:
    producer: ProducerIdentity
    candidates: tuple[Mapping[str, Any], ...]
    """Raw producer output in canonical order. Admission validates each one (R-2)."""
    excluded: tuple[ProducerExclusion, ...]


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    id: str
    kind: str
    items: tuple[str, ...]
    fact: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    policy_producer: str
    allow_list_version: str
    allowed_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Placement:
    slot: str
    wrap: str


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    version: int
    route: str
    model_family: str | None
    route_policy_version: str
    placement: tuple[Placement, ...]
    evaluation: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    route: str
    version: str
    document: Mapping[str, Any]
    """The full policy as supplied. Its fields are defined as later milestones use them."""
