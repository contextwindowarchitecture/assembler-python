"""R-22 timings without a clock in the core (D-9): the caller may lend assemble() a monotonic clock,
and only then does the trace carry timings. They are outside the payload and hash (R-23)."""
from __future__ import annotations

import itertools

import pytest

from cwa import Snapshot, assemble


def ticking(*seconds: float):
    """A fake monotonic clock that returns the given readings in turn."""
    readings = iter(seconds)
    return lambda: next(readings)


def test_without_a_clock_the_trace_has_no_timings(fixture_snapshot):
    assert "timings" not in assemble(Snapshot.from_json(fixture_snapshot)).trace


def test_a_lent_clock_times_each_stage_in_milliseconds(fixture_snapshot):
    trace = assemble(Snapshot.from_json(fixture_snapshot), clock=ticking(10.0, 10.001, 10.003, 10.006, 10.010, 10.015, 10.021)).trace
    assert trace["timings"] == pytest.approx(
        {"admission_ms": 1.0, "conflicts_ms": 2.0, "supersede_ms": 3.0, "dedupe_ms": 4.0, "fitting_ms": 5.0, "render_ms": 6.0})


def test_a_refusal_times_only_the_stages_that_ran(fixture_snapshot):
    fixture_snapshot["batches"][3]["items"].clear()  # no query: required_slot_missing
    result = assemble(Snapshot.from_json(fixture_snapshot), clock=ticking(0.0, 0.5, 1.0, 1.5, 2.0, 2.5))
    assert result.refused
    assert result.trace["timings"] == pytest.approx(
        {"admission_ms": 500.0, "conflicts_ms": 500.0, "supersede_ms": 500.0, "dedupe_ms": 500.0, "fitting_ms": 500.0})


def test_a_clock_that_runs_backwards_records_zero(fixture_snapshot):
    trace = assemble(Snapshot.from_json(fixture_snapshot), clock=ticking(5.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0)).trace
    assert trace["timings"]["admission_ms"] == 0


def test_timings_never_change_the_payload_or_the_rest_of_the_trace(fixture_snapshot):
    snapshot = Snapshot.from_json(fixture_snapshot)
    plain = assemble(snapshot, trace_id="t")
    timed = assemble(snapshot, trace_id="t", clock=itertools.count().__next__)
    assert timed.payload == plain.payload
    assert {k: v for k, v in timed.trace.items() if k != "timings"} == plain.trace
