"""Every trace the assembler emits names its exclusions and refusals with registered codes (R-21)."""
import copy

import pytest

from cwa import Snapshot, assemble
from cwa.trace import TraceError, validate


@pytest.fixture
def trace(fixture_snapshot) -> dict:
    return assemble(Snapshot.from_json(fixture_snapshot), trace_id="t").trace


def _with_row(trace: dict, **row) -> dict:
    trace = copy.deepcopy(trace)
    trace["excluded"].append({"item_id": "x", **row})
    return trace


def _refused(trace: dict, reason: str) -> dict:
    trace = copy.deepcopy(trace)
    trace.update(result=None, included=[], compressed=[], refused={"bool": True, "reason": reason})
    return trace


def test_assembler_rows_use_registered_exclusion_codes(trace):
    validate(_with_row(trace, reason="over_budget", stage="assembler"))
    validate(_with_row(trace, reason="missing_field:expires", stage="assembler"))
    for reason in ("too_long", "required_slot_missing", "missing_field:"):
        with pytest.raises(TraceError, match=reason):
            validate(_with_row(trace, reason=reason, stage="assembler"))


def test_producer_rows_keep_whatever_the_producer_reported(trace):
    validate(_with_row(trace, reason="retriever_timeout", stage="producer"))


def test_refusals_use_registered_refusal_codes(trace):
    validate(_refused(trace, "required_slot_missing"))
    for reason in ("out_of_tokens", "over_budget"):
        with pytest.raises(TraceError, match=reason):
            validate(_refused(trace, reason))
