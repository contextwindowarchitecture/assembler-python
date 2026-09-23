"""assemble(): a pure function from a frozen Snapshot to a payload and a trace.

M0 walking skeleton. It places, renders, counts, hashes and traces. Admission (M1), budget fitting
(M2) and conflict resolution (M3) are not implemented yet, so any snapshot that would need them
raises NotImplementedError rather than producing a payload the spec would not allow.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from .render import Occurrence
from .snapshot import Snapshot
from .trace import validate


@dataclass(frozen=True)
class AssemblyResult:
    payload: bytes | None
    trace: dict[str, Any]

    @property
    def refused(self) -> bool:
        return self.trace["refused"]["bool"]


def assemble(snapshot: Snapshot, *, trace_id: str | None = None) -> AssemblyResult:
    items = [item for batch in snapshot.batches for item in batch.items]
    placed = {placement.slot for placement in snapshot.profile.placement}
    if unplaced := sorted({item.slot for item in items} - placed):
        raise NotImplementedError(f"items in unplaced slots {unplaced} need admission (M1)")
    if snapshot.conflicts:
        raise NotImplementedError("conflict resolution lands in M3")

    occurrences = tuple(
        Occurrence(position, placement.slot, placement.wrap, item)
        for position, placement in enumerate(snapshot.profile.placement)
        for item in sorted((i for i in items if i.slot == placement.slot), key=lambda i: i.id)
    )
    rendered = snapshot.renderer.render(occurrences)
    input_tokens = snapshot.tokenizer.count(rendered.payload.decode("utf-8"))
    if input_tokens > snapshot.budget.input:
        raise NotImplementedError("budget fitting lands in M2")

    trace = {
        "trace_id": trace_id or str(uuid.uuid4()),
        "profile": {"id": snapshot.profile.id, "version": snapshot.profile.version},
        "budget": {"input": snapshot.budget.input, "reserved_output": snapshot.budget.reserved_output},
        "result": {"input_tokens": input_tokens, "hash": hashlib.sha256(rendered.payload).hexdigest()},
        "included": [
            {"slot": o.slot, "item_id": o.item.id, "tokens": snapshot.tokenizer.count(body), "source_version": o.item.source_version}
            for o, body in zip(occurrences, rendered.bodies)
        ],
        "compressed": [],
        "excluded": [
            {"item_id": row.item_id, "reason": row.reason, "stage": row.stage}
            for batch in snapshot.batches for row in batch.excluded
        ],
        "conflicts": [],
        "refused": {"bool": False, "reason": None},
        "context": {
            "assembly_time": snapshot.assembly_time,
            "route_policy_version": snapshot.route_policy.version,
            "tokenizer": snapshot.tokenizer.id,
            "renderer": snapshot.renderer.id,
            "snapshot_digest": snapshot.digest(),
        },
        "defaults_filled": [{"item_id": item.id, "field": field} for item in sorted(items, key=lambda i: i.id) for field in item.defaults_filled],
    }
    validate(trace)
    return AssemblyResult(payload=rendered.payload, trace=trace)
