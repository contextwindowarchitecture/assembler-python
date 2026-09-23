"""Route-requested supersession of stale observations, after conflicts and before deduplication (R-25).

conformance/README.md's Supersession section is the procedure this follows. A call is one authenticated
producer and one source: source is item-controlled, so it never lets one producer supersede another's
items (R-15). Instants compare at full precision (R-2).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Mapping

from . import instants
from .fitting import ranked, tier
from .model import Item
from .snapshot import Snapshot
from .strings import utf16


@dataclass(frozen=True, slots=True)
class Supersession:
    items: tuple[Item, ...]
    """The items that remain, in the order they arrived."""
    excluded: tuple[tuple[Item, str], ...]
    """(item, id of the latest item kept for its call) for each superseded item, in item id order."""


def supersede(snapshot: Snapshot, items: tuple[Item, ...], producers: Mapping[str, str]) -> Supersession:
    """producers: the authenticated producer of each item, by item id."""
    named = {item_id for group in snapshot.conflicts for item_id in group.items}
    exempt = lambda item: item.id in named or tier(snapshot, item) == "protected"
    by_freshness = cmp_to_key(lambda a, b: instants.compare(a.freshness, b.freshness))
    kept_for: dict[str, tuple[Item, str]] = {}
    for slot, rules in snapshot.route_policy.document.get("slots", {}).items():
        if rules.get("supersede") != "source":
            continue
        calls: dict[tuple[str, str], list[Item]] = {}
        for item in items:
            if item.slot == slot:
                calls.setdefault((producers[item.id], item.source), []).append(item)
        for members in calls.values():
            latest = max(members, key=by_freshness).freshness
            newest = [item for item in members if instants.compare(item.freshness, latest) == 0]
            kept = ranked(snapshot, slot, newest)[0].id
            kept_for.update({item.id: (item, kept) for item in members
                             if instants.compare(item.freshness, latest) < 0 and not exempt(item)})
    return Supersession(items=tuple(item for item in items if item.id not in kept_for),
                        excluded=tuple(kept_for[i] for i in sorted(kept_for, key=utf16)))
