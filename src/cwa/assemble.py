"""assemble(): a pure function from a frozen Snapshot to a payload and a trace.

It admits (placement last), resolves declared conflicts, removes the stale observations and duplicates and caps the sources the
route asks for, checks required slots and placement, fits the budget, checks evidence, places, renders, counts, hashes and traces.
"""
from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, Callable

from .admission import Admission, admit
from .conflicts import Resolution, resolve
from .dedupe import Deduplication, deduplicate
from .diversity import Diversity, cap_sources
from .supersede import Supersession, supersede
from .fitting import Compression, Fitted, fit
from .model import Item
from .render import Occurrence, place
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


def _missing_required(snapshot: Snapshot, items: tuple[Item, ...]) -> bool:
    return any(not any(item.slot == slot for item in items) for slot in _required_slots(snapshot))


_EVIDENCE = ("evidence.knowledge", "evidence.tool_results")


def _evidence_recovery(snapshot: Snapshot, fitted: Fitted) -> str | None:
    """The recovery action when a route that requires evidence is left without enough, else None (R-12)."""
    policy = snapshot.route_policy.document
    if not policy.get("requires_evidence", False):
        return None
    counts = Counter(item.slot for item in fitted.items if item.slot in _EVIDENCE)
    minimums = {slot: policy.get("slots", {}).get(slot, {}).get("min_included", 0) for slot in _EVIDENCE}
    if counts.total() and all(counts[slot] >= minimum for slot, minimum in minimums.items()):
        return None
    lost = [item for item in fitted.omitted if item.slot in _EVIDENCE]
    if not lost:
        return "request_context"  # producers or admission left too little
    return "precompute_summary" if any(not item.variants for item in lost) else "retrieve_narrower"


def _refusal(snapshot: Snapshot, resolution: Resolution, items: tuple[Item, ...]) -> tuple[str | None, Fitted | None, str | None]:
    """(reason, fitted, recovery action): the first refusal that holds, checked in contract/reasons.json
    order (R-21), and the fitting that later checks needed. items: what deduplication left."""
    if _missing_required(snapshot, items):
        return "required_slot_missing", None, None
    # R-20: admission keeps an item in an unplaced slot only when it is protected.
    if any(item.slot not in {p.slot for p in snapshot.profile.placement} for item in items):
        return "protected_slot_unplaced", None, None
    if resolution.refusing:
        # R-11: more context helps only if every refusing group asked for it.
        asked = all(action == "request_context" for action in resolution.refusing)
        return "conflict_unresolved", None, "request_context" if asked else None
    fitted = fit(snapshot, items, resolution.marks)
    if fitted.refusal:
        # A floor refusal keeps the omissions fitting made (R-17); a protected refusal has none.
        return fitted.refusal, fitted, None
    if recovery := _evidence_recovery(snapshot, fitted):
        return "evidence_required", fitted, recovery
    return None, fitted, None


def _trace(snapshot: Snapshot, admission: Admission, resolution: Resolution, supersession: Supersession, deduplication: Deduplication,
           diversity: Diversity, trace_id: str | None,
           omitted: tuple[Item, ...] = (), **outcome: Any) -> dict[str, Any]:
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
        ] + [{"item_id": item.id, "reason": reason, "stage": "assembler", "slot": item.slot} for item, reason in resolution.excluded
        ] + [{"item_id": item.id, "reason": "superseded", "stage": "assembler", "slot": item.slot, "superseded_by": kept}
             for item, kept in supersession.excluded
        ] + [{"item_id": item.id, "reason": "duplicate_content", "stage": "assembler", "slot": item.slot, "duplicate_of": kept}
             for item, kept in deduplication.excluded
        ] + [{"item_id": item.id, "reason": "source_diversity_cap", "stage": "assembler", "slot": item.slot} for item in diversity.excluded
        ] + [{"item_id": item.id, "reason": "over_budget", "stage": "assembler", "slot": item.slot} for item in omitted],
        "conflicts": [dict(record) for record in resolution.records],
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


def _original_body(snapshot: Snapshot, occurrence: Occurrence, compression: Compression) -> str:
    """The item's own body as this occurrence renders it, for compressed[].from (R-18)."""
    original = replace(occurrence.item, body=compression.original_body)
    return snapshot.renderer.render((replace(occurrence, item=original),)).bodies[0]


class _Stopwatch:
    """Stage timings from a clock the caller lends (R-22, D-9). Without one, nothing reads a clock
    and the trace has no timings. A clock that runs backwards records 0, never a negative time."""

    def __init__(self, clock: Callable[[], float] | None):
        self._clock, self._timings = clock, {}
        self._last = clock() if clock else 0.0

    def lap(self, stage: str) -> None:
        if self._clock:
            now = self._clock()
            self._timings[f"{stage}_ms"] = max(0.0, (now - self._last) * 1000)
            self._last = now

    def recorded(self) -> dict[str, Any]:
        return {"timings": self._timings} if self._clock else {}


def assemble(snapshot: Snapshot, *, trace_id: str | None = None, clock: Callable[[], float] | None = None) -> AssemblyResult:
    """clock, when given, is a monotonic clock in seconds, such as time.perf_counter. It only times
    the stages; nothing it returns reaches the payload (R-23)."""
    watch = _Stopwatch(clock)
    admission = admit(snapshot)
    items = admission.items
    watch.lap("admission")
    # Conflicts resolve before any refusal check, so every trace records them (R-11).
    resolution = resolve(snapshot, items, admission.producers)
    watch.lap("conflicts")
    # R-25, then R-24: after conflicts, so a group never loses a member to an ungoverned copy; before any refusal check.
    supersession = supersede(snapshot, resolution.items, admission.producers)
    watch.lap("supersede")
    deduplication = deduplicate(snapshot, supersession.items)
    watch.lap("dedupe")
    diversity = cap_sources(snapshot, deduplication.items, admission.producers)  # R-26: after dedupe, so a copy takes no place
    watch.lap("diversity")
    reason, fitted, recovery = _refusal(snapshot, resolution, diversity.items)
    watch.lap("fitting")  # the refusal checks, and fitting when they reach it
    if reason:
        # R-17: a refusal has no payload; exclusions found so far, including fitting's, stay in the trace.
        outcome = {"refused": {"bool": True, "reason": reason}, **({"recovery": {"action": recovery}} if recovery else {})}
        return AssemblyResult(payload=None, trace=_trace(snapshot, admission, resolution, supersession, deduplication, diversity, trace_id, fitted.omitted if fitted else (),
                                                         **outcome, **watch.recorded()))

    occurrences = place(snapshot.profile, fitted.items, resolution.marks)
    rendered = snapshot.renderer.render(occurrences)
    input_tokens = rendered.tokens(snapshot.tokenizer)
    watch.lap("render")

    return AssemblyResult(payload=rendered.payload, trace=_trace(
        snapshot, admission, resolution, supersession, deduplication, diversity, trace_id, fitted.omitted, **watch.recorded(),
        result={"input_tokens": input_tokens, "hash": hashlib.sha256(rendered.payload).hexdigest()},
        included=[
            {"slot": o.slot, "item_id": o.item.id, "tokens": snapshot.tokenizer.count(body), "source_version": o.item.source_version,
             "eligibility": o.item.eligibility}
            for o, body in zip(occurrences, rendered.bodies)
        ],
        compressed=[
            {"slot": o.slot, "item_id": o.item.id, "from": snapshot.tokenizer.count(_original_body(snapshot, o, c)), "to": snapshot.tokenizer.count(body),
             "method": c.variant.method, "variant_id": c.variant.id}
            for o, body in zip(occurrences, rendered.bodies) if (c := fitted.compressed.get(o.item.id))
        ],
    ))
