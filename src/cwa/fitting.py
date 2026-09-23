"""Fitting: reduce admitted items until the rendered payload fits budget.input (R-16, R-17).

"Fits" always means the whole payload, rendered and counted with the snapshot's tokenizer
(conformance/README.md, Fitting).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Callable, Iterable

from . import instants
from .contract import SLOT_DEFAULTS
from .model import Item
from .render import place
from .snapshot import Snapshot

TIER_RANK = {"droppable": 0, "compressible": 1, "protected": 2}


def slot_tier(snapshot: Snapshot, slot: str) -> str:
    """The slot's default tier, raised by the route's tier_upgrades (R-16)."""
    default = SLOT_DEFAULTS[slot]["tier"]
    upgrade = snapshot.route_policy.document.get("tier_upgrades", {}).get(slot, default)
    return max(default, upgrade, key=TIER_RANK.__getitem__)


def tier(snapshot: Snapshot, item: Item) -> str:
    return item.tier or slot_tier(snapshot, item.slot)


def tokens(snapshot: Snapshot, items: Iterable[Item]) -> int:
    rendered = snapshot.renderer.render(place(snapshot.profile, items))
    return snapshot.tokenizer.count(rendered.payload.decode("utf-8"))


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
        return next((c for key in keys if (c := key(a, b))), _sign(a.id, b.id))

    return sorted((item for item in items if item.slot == slot), key=cmp_to_key(compare))


def _slots_in_shedding_order(snapshot: Snapshot) -> list[str]:
    return sorted(SLOT_DEFAULTS, key=lambda slot: (_rules(snapshot, slot).get("priority", 0), slot))


def _shedding_order(snapshot: Snapshot, items: Iterable[Item]) -> list[Item]:
    """Slots by ascending priority, then name; within a slot, lowest rank first."""
    items = list(items)
    return [item for slot in _slots_in_shedding_order(snapshot) for item in reversed(_ranked(snapshot, slot, items))]


@dataclass(frozen=True, slots=True)
class Fitted:
    items: tuple[Item, ...]
    omitted: tuple[Item, ...] = ()
    """Items omitted for budget, in the order they were omitted."""
    refusal: str | None = None


def fit(snapshot: Snapshot, items: tuple[Item, ...]) -> Fitted:
    fits = lambda selection: tokens(snapshot, selection) <= snapshot.budget.input
    if not fits(i for i in items if tier(snapshot, i) == "protected"):
        # R-17: refuse before shedding anything, so the trace has no over_budget rows.
        return Fitted(items=(), refusal="protected_content_over_budget")
    kept = {item.id: item for item in items}
    omitted: list[Item] = []
    # R-16: every droppable item goes, one at a time, before any compressible item is reduced.
    for item in _shedding_order(snapshot, (i for i in items if tier(snapshot, i) == "droppable")):
        if fits(kept.values()):
            break
        omitted.append(kept.pop(item.id))
    if not fits(kept.values()):
        raise NotImplementedError("reducing compressible items lands later in M2")
    return Fitted(items=tuple(kept.values()), omitted=tuple(omitted))
