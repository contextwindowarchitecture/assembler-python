"""Route-requested source diversity, right after deduplication (R-26).

conformance/README.md's Source diversity section is the procedure this follows. A source is one
authenticated producer and one source, as supersession groups a call, so one producer's source strings
never crowd out another producer's items (R-15).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .fitting import ranked, tier
from .model import Item
from .snapshot import Snapshot
from .strings import utf16


@dataclass(frozen=True, slots=True)
class Diversity:
    items: tuple[Item, ...]
    """The items that remain, in the order they arrived."""
    excluded: tuple[Item, ...]
    """The items past their source's cap, in item id order."""


def cap_sources(snapshot: Snapshot, items: tuple[Item, ...], producers: Mapping[str, str]) -> Diversity:
    """producers: the authenticated producer of each item, by item id."""
    named = {item_id for group in snapshot.conflicts for item_id in group.items}
    exempt = lambda item: item.id in named or tier(snapshot, item) == "protected"
    over: dict[str, Item] = {}
    for slot, rules in snapshot.route_policy.document.get("slots", {}).items():
        if "max_per_source" not in rules:
            continue
        cap = int(rules["max_per_source"])  # read as a double, so 2.0 caps like 2 (conformance/README.md, Numbers)
        sources: dict[tuple[str, str], list[Item]] = {}
        for item in ranked(snapshot, slot, items):
            sources.setdefault((producers[item.id], item.source), []).append(item)
        for members in sources.values():
            places = max(0, cap - sum(map(exempt, members)))
            over.update({item.id: item for item in [m for m in members if not exempt(m)][places:]})
    return Diversity(items=tuple(item for item in items if item.id not in over),
                     excluded=tuple(over[i] for i in sorted(over, key=utf16)))
