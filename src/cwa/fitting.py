"""Fitting: reduce admitted items until the rendered payload fits budget.input (R-16, R-17).

"Fits" always means the whole payload, rendered and counted with the snapshot's tokenizer
(conformance/README.md, Fitting).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cmp_to_key
from typing import Callable, Iterable, Mapping

from . import instants
from .canonical import utf16
from .contract import SLOT_DEFAULTS
from .model import Item, Variant
from .render import Occurrence, place
from .snapshot import Snapshot

TIER_RANK = {"droppable": 0, "compressible": 1, "protected": 2}


def slot_tier(snapshot: Snapshot, slot: str) -> str:
    """The slot's default tier, raised by the route's tier_upgrades (R-16)."""
    default = SLOT_DEFAULTS[slot]["tier"]
    upgrade = snapshot.route_policy.document.get("tier_upgrades", {}).get(slot, default)
    return max(default, upgrade, key=TIER_RANK.__getitem__)


def tier(snapshot: Snapshot, item: Item) -> str:
    return item.tier or slot_tier(snapshot, item.slot)


def tokens(snapshot: Snapshot, items: Iterable[Item], marks: Mapping[str, str] | None = None) -> int:
    rendered = snapshot.renderer.render(place(snapshot.profile, items, marks))
    return rendered.tokens(snapshot.tokenizer)


def body_tokens(snapshot: Snapshot, item: Item) -> int:
    """Tokens in the item's rendered body: the largest of its occurrences' renderings, since a
    cap bounds the body however it is rendered (R-3, R-16)."""
    occurrences = tuple(Occurrence(n, p.slot, p.wrap, item) for n, p in enumerate(snapshot.profile.placement) if p.slot == item.slot)
    return max(snapshot.tokenizer.count(body) for body in snapshot.renderer.render(occurrences).bodies)


def _sign(a: object, b: object) -> int:
    return (a > b) - (a < b)


def _by_relevance(a: Item, b: Item) -> int:
    # Higher scores rank first; unscored items rank last.
    if a.relevance is None or b.relevance is None:
        return _sign(a.relevance is None, b.relevance is None)
    return _sign(b.relevance, a.relevance)


_ORDER_KEYS: dict[str, Callable[[Item, Item], int]] = {
    "-relevance": _by_relevance,
    "-freshness": lambda a, b: instants.compare(b.freshness, a.freshness),
    "freshness": lambda a, b: instants.compare(a.freshness, b.freshness),
}


def _rules(snapshot: Snapshot, slot: str) -> dict:
    return snapshot.route_policy.document.get("slots", {}).get(slot, {})


def _ranked(snapshot: Snapshot, slot: str, items: Iterable[Item]) -> list[Item]:
    """The slot's items, highest rank first: order_by keys, then id (R-16)."""
    keys = [_ORDER_KEYS[key] for key in _rules(snapshot, slot).get("order_by", ["-relevance", "-freshness"])]

    def compare(a: Item, b: Item) -> int:
        return next((c for key in keys if (c := key(a, b))), _sign(utf16(a.id), utf16(b.id)))

    return sorted((item for item in items if item.slot == slot), key=cmp_to_key(compare))


def _slots_in_shedding_order(snapshot: Snapshot) -> list[str]:
    return sorted(SLOT_DEFAULTS, key=lambda slot: (_rules(snapshot, slot).get("priority", 0), slot))


def _shedding_order(snapshot: Snapshot, items: Iterable[Item]) -> list[Item]:
    """Slots by ascending priority, then name; within a slot, lowest rank first."""
    items = list(items)
    return [item for slot in _slots_in_shedding_order(snapshot) for item in reversed(_ranked(snapshot, slot, items))]


def _steps(snapshot: Snapshot) -> list[tuple[str, str]]:
    """The route's fitting_order, then compress each slot and omit each slot in shedding order,
    skipping steps the route listed (R-16). Without a route order, variants come before omission."""
    listed = [(step["slot"], step["action"]) for step in snapshot.route_policy.document.get("fitting_order", [])]
    order = _slots_in_shedding_order(snapshot)
    default = [(slot, "compress") for slot in order] + [(slot, "omit") for slot in order]
    return listed + [step for step in default if step not in listed]


@dataclass(frozen=True, slots=True)
class Compression:
    variant: Variant
    original_body: str
    """The item's own body, which each occurrence renders for compressed[].from (R-18)."""


@dataclass(frozen=True, slots=True)
class Fitted:
    items: tuple[Item, ...]
    """Kept items; a compressed item carries its variant's body under its own id."""
    omitted: tuple[Item, ...] = ()
    """Items omitted for budget, in the order they were omitted."""
    compressed: Mapping[str, Compression] = field(default_factory=dict)
    """The variant each kept, compressed item uses, by item id (R-18)."""
    refusal: str | None = None


def _over_cap(snapshot: Snapshot, item: Item) -> bool:
    return item.token_budget is not None and body_tokens(snapshot, item) > item.token_budget


def fit(snapshot: Snapshot, items: tuple[Item, ...], marks: Mapping[str, str] | None = None) -> Fitted:
    """marks: surfaced conflict members by id, whose marks count against the budget like any wrapper."""
    fits = lambda selection: tokens(snapshot, selection, marks) <= snapshot.budget.input
    protected = [i for i in items if tier(snapshot, i) == "protected"]
    if any(_over_cap(snapshot, i) for i in protected) or not fits(protected):
        # R-17: refuse before shedding anything, so the trace has no over_budget rows.
        return Fitted(items=(), refusal="protected_content_over_budget")
    kept = {item.id: item for item in items}
    omitted: list[Item] = []
    compressed: dict[str, Compression] = {}
    # R-16: token_budget caps hold whether or not the payload fits.
    for item in _shedding_order(snapshot, (i for i in items if i not in protected and _over_cap(snapshot, i))):
        within = [(n, index, variant) for index, variant in enumerate(item.variants)
                  if (n := body_tokens(snapshot, replace(item, body=variant.body))) <= item.token_budget]
        if tier(snapshot, item) == "compressible" and within:
            variant = max(within, key=lambda s: (s[0], -s[1]))[2]
            kept[item.id] = replace(item, body=variant.body)
            compressed[item.id] = Compression(variant, item.body)
        else:
            omitted.append(kept.pop(item.id))
    # R-16: every droppable item goes, one at a time, before any compressible item is reduced.
    for item in _shedding_order(snapshot, [i for i in kept.values() if tier(snapshot, i) == "droppable"]):
        if fits(kept.values()):
            break
        omitted.append(kept.pop(item.id))
    for slot, action in _steps(snapshot):
        for item in reversed(_ranked(snapshot, slot, (i for i in kept.values() if tier(snapshot, i) == "compressible"))):
            if fits(kept.values()):
                break
            if action == "omit":
                omitted.append(kept.pop(item.id))
                compressed.pop(item.id, None)
            elif variant := _compress(snapshot, item, kept, fits):
                original = compressed[item.id].original_body if item.id in compressed else item.body
                kept[item.id] = replace(item, body=variant.body)
                compressed[item.id] = Compression(variant, original)
    # Only protected items can remain once every step has run, and those fit.
    assert fits(kept.values())
    return Fitted(items=tuple(kept.values()), omitted=tuple(omitted), compressed=compressed)


def _compress(snapshot: Snapshot, item: Item, kept: Mapping[str, Item], fits: Callable[[Iterable[Item]], bool]) -> Variant | None:
    """The longest supplied variant shorter than the current body that makes the payload fit, else the
    shortest; earlier variants win ties. None when no variant is shorter (R-16, R-18)."""
    current = body_tokens(snapshot, item)
    shorter = [(n, index, variant) for index, variant in enumerate(item.variants)
               if (n := body_tokens(snapshot, replace(item, body=variant.body))) < current]
    if not shorter:
        return None
    fitting = (v for _, _, v in sorted(shorter, key=lambda s: (-s[0], s[1]))
               if fits({**kept, item.id: replace(item, body=v.body)}.values()))
    return next(fitting, min(shorter, key=lambda s: (s[0], s[1]))[2])
