"""Conflict resolution for the groups the application declared (R-6, R-11).

It never reads a body: every decision comes from authority, conflict_policy and route policy.
conformance/README.md's Conflicts section is the procedure this follows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .fitting import tier
from .model import ConflictGroup, Item
from .snapshot import Snapshot

# R-6: only these may instruct; state, evidence, memory and untrusted content stay material.
_INSTRUCTING = ("governing", "user")


@dataclass(frozen=True, slots=True)
class Resolution:
    records: tuple[Mapping[str, Any], ...]
    """One trace conflicts[] record per declared group, in group id order."""
    items: tuple[Item, ...]
    """The admitted items that remain for fitting."""
    excluded: tuple[tuple[Item, str], ...]
    """(item, reason) for each item a group excluded, in item id order."""


class _Escalate(Exception):
    """The group has no unique supported resolution (R-11)."""


def _record(group: ConflictGroup, decided_by: str, resolution: str, winner: str | None = None) -> dict[str, Any]:
    return {"group_id": group.id, "kind": group.kind, "items": list(group.items), "decided_by": decided_by,
            "resolution": resolution, **({"winner": winner} if winner else {})}


def _instruction(snapshot: Snapshot, group: ConflictGroup, members: list[Item]) -> tuple[dict[str, Any], list[tuple[Item, str]]]:
    instructing = [m for m in members if m.authority in _INSTRUCTING]
    top = next((a for a in _INSTRUCTING if any(m.authority == a for m in instructing)), None)
    peers = [m for m in instructing if m.authority == top]
    if len(peers) < 2:
        return _record(group, "authority", "resolved", peers[0].id if peers else None), []
    governing = [m for m in peers if m.conflict_policy == "governs"]
    deferring = [m for m in peers if m.conflict_policy == "defers"]
    if len(governing) != 1 or len(deferring) != len(peers) - 1:
        raise _Escalate
    if any(tier(snapshot, m) == "protected" for m in deferring):
        raise _Escalate
    return _record(group, "policy", "resolved", governing[0].id), [(m, "conflict_deferred") for m in deferring]


def resolve(snapshot: Snapshot, items: tuple[Item, ...]) -> Resolution:
    """Decide every declared group against the admitted items."""
    admitted = {item.id: item for item in items}
    records, excluded = [], []
    for group in snapshot.conflicts:
        members = [admitted[i] for i in group.items if i in admitted]
        if len(members) < 2:
            records.append(_record(group, "moot", "moot"))
            continue
        if group.kind == "fact":
            raise NotImplementedError("fact groups land later in M3")
        try:
            record, losers = _instruction(snapshot, group, members)
        except _Escalate:
            raise NotImplementedError("escalated conflict groups land later in M3") from None
        records.append(record)
        excluded += losers
    excluded.sort(key=lambda row: row[0].id)
    gone = {item.id for item, _ in excluded}
    return Resolution(records=tuple(records), items=tuple(i for i in items if i.id not in gone), excluded=tuple(excluded))
