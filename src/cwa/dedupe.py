"""Route-requested exact deduplication, right after conflict resolution (R-24).

conformance/README.md's Deduplication section is the procedure this follows. Keys collapse only
ECMAScript whitespace and never normalize Unicode, so every runtime computes the same keys.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .fitting import ranked, tier
from .model import Item
from .snapshot import Snapshot
from .strings import WHITESPACE, utf16

_RUN = re.compile(f"[{WHITESPACE}]+")


@dataclass(frozen=True, slots=True)
class Deduplication:
    items: tuple[Item, ...]
    """The items that remain, in the order they arrived."""
    excluded: tuple[tuple[Item, str], ...]
    """(item, id of the item kept in its place) for each duplicate, in item id order."""


def key(body: str) -> str:
    """Whitespace runs collapsed to one space, and the ends trimmed."""
    return _RUN.sub(" ", body).strip(" ")


def deduplicate(snapshot: Snapshot, items: tuple[Item, ...]) -> Deduplication:
    named = {item_id for group in snapshot.conflicts for item_id in group.items}
    exempt = lambda item: item.id in named or tier(snapshot, item) == "protected"
    kept_for: dict[str, tuple[Item, str]] = {}
    for slot, rules in snapshot.route_policy.document.get("slots", {}).items():
        if rules.get("dedupe") != "exact":
            continue
        sets: dict[str, list[Item]] = {}
        for item in ranked(snapshot, slot, items):
            sets.setdefault(key(item.body), []).append(item)
        for members in sets.values():
            keep = [item for item in members if exempt(item)] or members[:1]
            kept_for.update({item.id: (item, keep[0].id) for item in members if item.id not in {k.id for k in keep}})
    return Deduplication(items=tuple(item for item in items if item.id not in kept_for),
                         excluded=tuple(kept_for[i] for i in sorted(kept_for, key=utf16)))
