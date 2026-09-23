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
from . import instants
from .canonical import utf16
from .fitting import TIER_RANK, slot_tier, tier
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
    slot: str | None
    """The candidate's slot when it names one of the eleven, whatever else is wrong with it (R-22)."""


@dataclass(frozen=True, slots=True)
class Admission:
    items: tuple[Item, ...]
    excluded: tuple[Exclusion, ...]
    """Assembler-stage exclusions, ordered by producer id and then recorded item id."""
    defaults_filled: tuple[tuple[str, str], ...]
    """(item id, field) for every schema-valid candidate whose policy fields were filled (R-3, R-22)."""
    producers: Mapping[str, str]
    """The authenticated producer id of each admitted item, by item id (R-15)."""


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


def _governance_trust(item: Item, ctx: _Context) -> str | None:
    # R-10: governance holds only verified content with no injection risk.
    if item.slot.startswith("governance.") and (item.trust != "verified" or item.injection_risk != "none"):
        return "untrusted_in_governance"
    return None


def _marking(item: Item, ctx: _Context) -> str | None:
    # R-10, R-15: content from these slots stays marked, unless the route verified this MCP server.
    verified_mcp = ctx.producer.kind == "mcp" and ctx.granted.get("verified", False)
    if SLOT_DEFAULTS[item.slot]["injection_risk"] == "untrusted_content" and item.injection_risk != "untrusted_content" and not verified_mcp:
        return "untrusted_content_unmarked"
    return None


def _protected_downgrade(item: Item, ctx: _Context) -> str | None:
    if SLOT_DEFAULTS[item.slot]["tier"] == "protected" and item.tier not in (None, "protected"):
        return "protected_tier_changed"
    return None


def _tier_upgrade(item: Item, ctx: _Context) -> str | None:
    # R-16: only the route raises a tier; an item may claim at most the slot's effective tier.
    if item.tier is not None and TIER_RANK[item.tier] > TIER_RANK[slot_tier(ctx.snapshot, item.slot)]:
        return "tier_upgrade_not_allowed"
    return None


def _variant_ids(item: Item, ctx: _Context) -> str | None:
    ids = [item.id, *(v.id for v in item.variants)]
    return "duplicate_variant_id" if len(set(ids)) != len(ids) else None


def _revoked(item: Item, ctx: _Context) -> str | None:
    return "revoked" if item.revoked_by is not None else None


def _expired(item: Item, ctx: _Context) -> str | None:
    # R-9: expires is exclusive at assembly_time, so equal means expired.
    if item.expires is not None and instants.compare(item.expires, ctx.snapshot.assembly_time) <= 0:
        return "expired"
    return None


def _future_freshness(item: Item, ctx: _Context) -> str | None:
    skew = ctx.snapshot.route_policy.document.get("clock_skew_seconds", 0)
    if instants.compare(item.freshness, ctx.snapshot.assembly_time, b_offset_seconds=skew) > 0:
        return "future_freshness"
    return None


def _slot_rules(item: Item, ctx: _Context) -> Mapping[str, Any]:
    return ctx.snapshot.route_policy.document.get("slots", {}).get(item.slot, {})


def _older_than_allowed(item: Item, ctx: _Context) -> bool:
    max_age = _slot_rules(item, ctx).get("max_age_seconds")
    return max_age is not None and instants.compare(item.freshness, ctx.snapshot.assembly_time, b_offset_seconds=-max_age) < 0


def _stale_state(item: Item, ctx: _Context) -> str | None:
    return "stale_state" if item.slot.startswith("state.") and _older_than_allowed(item, ctx) else None


def _source_prefix(item: Item, ctx: _Context) -> str | None:
    prefix = _slot_rules(item, ctx).get("source_prefix")
    return "source_invalid" if prefix is not None and not item.source.startswith(prefix) else None


def _scope(item: Item, ctx: _Context) -> str | None:
    request = ctx.snapshot.scope
    required = _slot_rules(item, ctx).get("required_scope", [])
    if any(key not in item.scope for key in required) or any(request.get(k) != v for k, v in item.scope.items()):
        return "out_of_scope"
    return None


def _threshold(item: Item, ctx: _Context) -> str | None:
    # R-13: an unscored item cannot show that it clears the route's threshold.
    minimum = _slot_rules(item, ctx).get("min_relevance")
    return "below_threshold" if minimum is not None and (item.relevance is None or item.relevance < minimum) else None


def _eligible(item: Item, ctx: _Context) -> str | None:
    # State age is stale_state above; elsewhere age is part of the route's eligibility predicate (R-3).
    return "not_eligible" if not item.slot.startswith("state.") and _older_than_allowed(item, ctx) else None


def _placed(item: Item, ctx: _Context) -> str | None:
    # R-20: a protected item stays admitted even when unplaced, so that assembly refuses rather than drop it.
    if item.slot not in {p.slot for p in ctx.snapshot.profile.placement} and tier(ctx.snapshot, item) != "protected":
        return "slot_unplaced"
    return None


# Checks for schema-valid items from authenticated producers, in reasons.json order.
_CHECKS: tuple[Callable[[Item, _Context], str | None], ...] = (
    _duplicate, _slot_permission, _authority, _capability, _governance_trust, _marking,
    _protected_downgrade, _tier_upgrade, _variant_ids, _revoked, _expired, _future_freshness,
    _stale_state, _source_prefix, _scope, _threshold, _eligible, _placed,
)


def _item_reason(item: Item, ctx: _Context) -> str | None:
    return next((reason for check in _CHECKS if (reason := check(item, ctx))), None)


def admit(snapshot: Snapshot) -> Admission:
    items, excluded, filled, producers = [], [], [], {}
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
            slot = candidate.get("slot")
            slot = slot if isinstance(slot, str) and slot in SLOT_DEFAULTS else None
            if not authenticated:
                excluded.append(Exclusion(batch.producer.id, item_id, "producer_not_authenticated", slot))
                continue
            if reason := _structure(candidate):
                excluded.append(Exclusion(batch.producer.id, item_id, reason, slot))
                continue
            overrides = snapshot.route_policy.document.get("default_overrides", {}).get(candidate["slot"])
            item = Item.from_json(candidate, overrides)
            filled += [(item.id, field) for field in item.defaults_filled]
            if reason := _item_reason(item, _Context(snapshot, batch.producer, granted, id_uses)):
                excluded.append(Exclusion(batch.producer.id, item_id, reason, slot))
                continue
            items.append(item)
            producers[item.id] = batch.producer.id
    return Admission(
        items=tuple(items),
        excluded=tuple(sorted(excluded, key=lambda e: (utf16(e.producer), utf16(e.item_id)))),
        defaults_filled=tuple(sorted(filled, key=lambda f: (utf16(f[0]), POLICY_FIELDS.index(f[1])))),
        producers=producers,
    )
