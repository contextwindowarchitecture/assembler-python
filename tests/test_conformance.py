"""Runs every vendored conformance case (conformance/README.md)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json

IGNORED = ("trace_id", "timings")

# Cases whose milestone is in progress. Strict: once a case passes, pytest fails until it is removed here.
PENDING: dict[str, str] = {
    "budget-droppable-order": "M2: budget fitting and refusal",
    "budget-omit-after-variants": "M2: budget fitting and refusal",
    "budget-route-order": "M2: budget fitting and refusal",
    "budget-variant-choice": "M2: budget fitting and refusal",
    "evidence-precompute-summary": "M2: budget fitting and refusal",
    "evidence-request-context": "M2: budget fitting and refusal",
    "evidence-retrieve-narrower": "M2: budget fitting and refusal",
}


def comparable(trace: dict) -> dict:
    trace = {k: v for k, v in trace.items() if k not in IGNORED}
    trace["context"] = {k: v for k, v in trace["context"].items() if k != "snapshot_digest"}
    return trace


@pytest.mark.parametrize("case", [
    pytest.param(name, marks=pytest.mark.xfail(reason=PENDING[name], strict=True)) if name in PENDING else name
    for name in sorted(p.name for p in CASES.iterdir())
])
def test_conformance_case(case: str) -> None:
    directory = CASES / case
    result = assemble(Snapshot.from_json(read_json(directory / "snapshot.json")))
    expected_payload = directory / "expected.payload.txt"
    if expected_payload.exists():
        assert result.payload == expected_payload.read_bytes()
    else:
        assert result.payload is None
    assert comparable(result.trace) == comparable(read_json(directory / "expected.trace.json"))
