"""assemble(): a pure function from a frozen Snapshot to a payload and a trace.

It admits, checks required slots, fits the budget, places, renders, counts, hashes and traces.
Conflict resolution (M3) is not implemented yet, so any snapshot that would need it raises
NotImplementedError rather than producing a payload the spec would not allow.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from .admission import Admission, admit
from .fitting import fit
from .model import Item
from .render import place
from .snapshot import Snapshot
from .trace import validate


@dataclass(frozen=True)
class AssemblyResult:
    payload: bytes | None
    trace: dict[str, Any]

    @property
    def refused(self) -> bool:
        return self.trace["refused"]["bool"]


def _required_slots(snapshot: Snapshot) -> tuple[str, ...]:
    # R-4: output_contract is required only where a downstream parser consumes the response.
    parser = snapshot.route_policy.document.get("parser", False)
    return ("governance.instructions", "interaction.query") + (("governance.output_contract",) if parser else ())


def _refusal(snapshot: Snapshot, items: tuple[Item, ...]) -> str | None:
    """The first refusal condition that holds, checked in contract/reasons.json order (R-21)."""
    if any(not any(item.slot == slot for item in items) for slot in _required_slots(snapshot)):
        return "required_slot_missing"
    return None


def _trace(snapshot: Snapshot, admission: Admission, trace_id: str | None, omitted: tuple[Item, ...] = (),
           **outcome: Any) -> dict[str, Any]:
    trace = {
        "trace_id": trace_id or str(uuid.uuid4()),
        "profile": {"id": snapshot.profile.id, "version": snapshot.profile.version},
        "budget": {"input": snapshot.budget.input, "reserved_output": snapshot.budget.reserved_output},
        "result": None,
        "included": [],
        "compressed": [],
        "excluded": [
            {"item_id": row.item_id, "reason": row.reason, "stage": row.stage}
            for batch in snapshot.batches for row in batch.excluded
        ] + [{"item_id": e.item_id, "reason": e.reason, "stage": "assembler", **({"slot": e.slot} if e.slot else {})}
             for e in admission.excluded
        ] + [{"item_id": item.id, "reason": "over_budget", "stage": "assembler", "slot": item.slot} for item in omitted],
        "conflicts": [],
        "refused": {"bool": False, "reason": None},
        "context": {
            "assembly_time": snapshot.assembly_time,
            "route_policy_version": snapshot.route_policy.version,
            "tokenizer": snapshot.tokenizer.id,
            "renderer": snapshot.renderer.id,
            "snapshot_digest": snapshot.digest(),
        },
        "defaults_filled": [{"item_id": item_id, "field": field} for item_id, field in admission.defaults_filled],
    }
    trace.update(outcome)
    validate(trace)
    return trace


def assemble(snapshot: Snapshot, *, trace_id: str | None = None) -> AssemblyResult:
    admission = admit(snapshot)
    items = admission.items
    placed = {placement.slot for placement in snapshot.profile.placement}
    if unplaced := sorted({item.slot for item in items} - placed):
        raise NotImplementedError(f"admitted items in unplaced slots {unplaced} need placement checks (M4)")
    if snapshot.conflicts:
        raise NotImplementedError("conflict resolution lands in M3")
    fitted = None
    if not (reason := _refusal(snapshot, items)):
        fitted = fit(snapshot, items)
        reason = fitted.refusal
    if reason:
        # R-17: a refusal has no payload; exclusions found so far stay in the trace.
        return AssemblyResult(payload=None, trace=_trace(snapshot, admission, trace_id, refused={"bool": True, "reason": reason}))

    occurrences = place(snapshot.profile, fitted.items)
    rendered = snapshot.renderer.render(occurrences)
    input_tokens = snapshot.tokenizer.count(rendered.payload.decode("utf-8"))

    return AssemblyResult(payload=rendered.payload, trace=_trace(
        snapshot, admission, trace_id, fitted.omitted,
        result={"input_tokens": input_tokens, "hash": hashlib.sha256(rendered.payload).hexdigest()},
        included=[
            {"slot": o.slot, "item_id": o.item.id, "tokens": snapshot.tokenizer.count(body), "source_version": o.item.source_version}
            for o, body in zip(occurrences, rendered.bodies)
        ],
    ))
