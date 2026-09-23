"""Conflict resolution for the groups the application declared (R-6, R-11).

It never reads a body: every decision comes from authority, conflict_policy and route policy.
conformance/README.md's Conflicts section is the procedure this follows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import instants
from .strings import utf16
from .fitting import tier
from .model import ConflictGroup, Item
from .snapshot import Snapshot

# R-6: only these may instruct; state, evidence, memory and untrusted content stay material.
_INSTRUCTING = ("governing", "user")
_ESCALATED = {"surface": "surfaced", "request_context": "context_requested", "refuse": "refused"}


@dataclass(frozen=True, slots=True)
class Resolution:
    records: tuple[Mapping[str, Any], ...]
    """One trace conflicts[] record per declared group, in group id order."""
    items: tuple[Item, ...]
    """The admitted items that remain for fitting."""
    excluded: tuple[tuple[Item, str], ...]
    """(item, reason) for each item a group excluded, in item id order."""
    marks: Mapping[str, str]
    """The group id of each member of a surfaced group, for the renderer to mark."""
    refusing: tuple[str, ...]
    """The on_unresolved action of each escalated group that refuses: request_context or refuse."""


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


def _fact(snapshot: Snapshot, group: ConflictGroup, members: list[Item], producers: Mapping[str, str]) -> tuple[dict[str, Any], list[tuple[Item, str]]]:
    policy = snapshot.route_policy.document["facts"][group.fact]
    precedence = policy["precedence"]
    # Eligibility reads the authenticated producer, never item.source (R-15).
    eligible = [m for m in members if producers[m.id] in precedence and all(key in m.scope for key in policy.get("scope", []))]
    if not eligible:
        raise _Escalate
    best = min(precedence.index(producers[m.id]) for m in eligible)
    leaders = [m for m in eligible if precedence.index(producers[m.id]) == best]
    decided_by = "policy"
    if len(leaders) > 1:
        newest = [m for m in leaders if all(instants.compare(m.freshness, other.freshness) > 0 for other in leaders if other is not m)]
        if not policy.get("freshness_tiebreak", False) or not newest:
            raise _Escalate
        leaders, decided_by = newest, "freshness"
    losers = [m for m in members if m is not leaders[0]]
    if any(tier(snapshot, m) == "protected" for m in losers):
        raise _Escalate
    return _record(group, decided_by, "resolved", leaders[0].id), [(m, "conflict_lost") for m in losers]


def resolve(snapshot: Snapshot, items: tuple[Item, ...], producers: Mapping[str, str]) -> Resolution:
    """Decide every declared group against the admitted items; producers maps each to its
    authenticated producer id."""
    admitted = {item.id: item for item in items}
    records, excluded, marks, refusing = [], [], {}, []
    for group in snapshot.conflicts:
        members = [admitted[i] for i in group.items if i in admitted]
        if len(members) < 2:
            records.append(_record(group, "moot", "moot"))
            continue
        try:
            if group.kind == "fact":
                record, losers = _fact(snapshot, group, members, producers)
            else:
                record, losers = _instruction(snapshot, group, members)
        except _Escalate:
            if group.kind == "fact":
                action = snapshot.route_policy.document["facts"][group.fact]["on_unresolved"]
            else:
                action = snapshot.route_policy.document.get("on_unresolved_instruction", "refuse")
            record, losers = _record(group, "escalated", _ESCALATED[action]), []
            if action == "surface":
                marks.update((m.id, group.id) for m in members)
            else:
                refusing.append(action)
        records.append(record)
        excluded += losers
    excluded.sort(key=lambda row: utf16(row[0].id))
    gone = {item.id for item, _ in excluded}
    return Resolution(records=tuple(records), items=tuple(i for i in items if i.id not in gone), excluded=tuple(excluded),
                      marks=marks, refusing=tuple(refusing))
