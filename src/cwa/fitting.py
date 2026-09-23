"""Fitting: reduce admitted items until the rendered payload fits budget.input (R-16, R-17).

"Fits" always means the whole payload, rendered and counted with the snapshot's tokenizer
(conformance/README.md, Fitting).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contract import SLOT_DEFAULTS
from .model import Item
from .render import place
from .snapshot import Snapshot

_TIER_RANK = {"droppable": 0, "compressible": 1, "protected": 2}


def slot_tier(snapshot: Snapshot, slot: str) -> str:
    """The slot's default tier, raised by the route's tier_upgrades (R-16)."""
    default = SLOT_DEFAULTS[slot]["tier"]
    upgrade = snapshot.route_policy.document.get("tier_upgrades", {}).get(slot, default)
    return max(default, upgrade, key=_TIER_RANK.__getitem__)


def tier(snapshot: Snapshot, item: Item) -> str:
    return item.tier or slot_tier(snapshot, item.slot)


def tokens(snapshot: Snapshot, items: Iterable[Item]) -> int:
    rendered = snapshot.renderer.render(place(snapshot.profile, items))
    return snapshot.tokenizer.count(rendered.payload.decode("utf-8"))


@dataclass(frozen=True, slots=True)
class Fitted:
    items: tuple[Item, ...]
    refusal: str | None = None


def fit(snapshot: Snapshot, items: tuple[Item, ...]) -> Fitted:
    fits = lambda selection: tokens(snapshot, selection) <= snapshot.budget.input
    if not fits(i for i in items if tier(snapshot, i) == "protected"):
        # R-17: refuse before shedding anything, so the trace has no over_budget rows.
        return Fitted(items=(), refusal="protected_content_over_budget")
    if not fits(items):
        raise NotImplementedError("shedding lands later in M2")
    return Fitted(items=items)
