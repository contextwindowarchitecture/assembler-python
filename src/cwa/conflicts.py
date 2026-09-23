"""Conflict resolution for the groups the application declared (R-6, R-11).

It never reads a body: every decision comes from authority, conflict_policy and route policy.
conformance/README.md's Conflicts section is the procedure this follows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .model import ConflictGroup, Item
from .snapshot import Snapshot

# R-6: only these may instruct; state, evidence, memory and untrusted content stay material.
_INSTRUCTING = ("governing", "user")


@dataclass(frozen=True, slots=True)
class Resolution:
    records: tuple[Mapping[str, Any], ...]
    """One trace conflicts[] record per declared group, in group id order."""


def _record(group: ConflictGroup, decided_by: str, resolution: str, winner: str | None = None) -> dict[str, Any]:
    return {"group_id": group.id, "kind": group.kind, "items": list(group.items), "decided_by": decided_by,
            "resolution": resolution, **({"winner": winner} if winner else {})}


def _instruction(group: ConflictGroup, members: list[Item]) -> dict[str, Any]:
    instructing = [m for m in members if m.authority in _INSTRUCTING]
    top = next((a for a in _INSTRUCTING if any(m.authority == a for m in instructing)), None)
    peers = [m for m in instructing if m.authority == top]
    if len(peers) > 1:
        raise NotImplementedError("instruction peers resolved by conflict_policy land later in M3")
    return _record(group, "authority", "resolved", peers[0].id if peers else None)


def resolve(snapshot: Snapshot, items: tuple[Item, ...]) -> Resolution:
    """Decide every declared group against the admitted items."""
    admitted = {item.id: item for item in items}
    records = []
    for group in snapshot.conflicts:
        members = [admitted[i] for i in group.items if i in admitted]
        if len(members) < 2:
            records.append(_record(group, "moot", "moot"))
        elif group.kind == "instruction":
            records.append(_instruction(group, members))
        else:
            raise NotImplementedError("fact groups land later in M3")
    return Resolution(records=tuple(records))
