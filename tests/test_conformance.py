"""Runs every vendored conformance case (conformance/README.md)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json

IGNORED = ("trace_id", "timings")


def comparable(trace: dict) -> dict:
    trace = {k: v for k, v in trace.items() if k not in IGNORED}
    trace["context"] = {k: v for k, v in trace["context"].items() if k != "snapshot_digest"}
    return trace


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_conformance_case(case: str) -> None:
    directory = CASES / case
    result = assemble(Snapshot.from_json(read_json(directory / "snapshot.json")))
    expected_payload = directory / "expected.payload.txt"
    if expected_payload.exists():
        assert result.payload == expected_payload.read_bytes()
    else:
        assert result.payload is None
    assert comparable(result.trace) == comparable(read_json(directory / "expected.trace.json"))
