"""Runs every vendored conformance case (conformance/README.md)."""
from __future__ import annotations

import copy
import random

import pytest

from cwa import Snapshot, SnapshotError, assemble
from cwa.conformance import comparable
from cwa.snapshot import usable_id
from cwa.trace import TraceError
from conftest import CASES, read_json

# Cases whose milestone is in progress. Strict: once a case passes, pytest fails until it is removed here.
PENDING: dict[str, str] = {
    "tokenizer-estimate-utf8": "M11: estimate-utf8/v1 is not provided yet",
}
# What a pending case may raise in place of an outcome: its milestone's gap, a trace the newer
# schema rejects, or a missing renderer or tokenizer, which conformance/README.md treats as a
# skipped case.
GAPS = (NotImplementedError, SnapshotError, TraceError)


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


def _shuffled(document: dict, rng: random.Random) -> dict:
    """The same snapshot as producers might return it: batches, candidates, producer exclusions,
    groups and group members in any order. Candidates without a usable id keep their relative
    order, which R-2 makes significant."""
    document = copy.deepcopy(document)
    rng.shuffle(document["batches"])
    for batch in document["batches"]:
        named = [c for c in batch["items"] if isinstance(c, dict) and usable_id(c)]
        rng.shuffle(named)
        batch["items"] = named + [c for c in batch["items"] if not any(c is n for n in named)]
        rng.shuffle(batch["excluded"])
    rng.shuffle(document["conflicts"])
    for group in document["conflicts"]:
        rng.shuffle(group["items"])
    return document


def _outcome(case: str, document: dict) -> tuple:
    """The payload and trace, or, for a pending case, the milestone gap it raises instead."""
    try:
        result = assemble(Snapshot.from_json(document), trace_id="t")
    except GAPS as gap:
        if case not in PENDING:
            raise
        return (type(gap).__name__, str(gap))
    return (result.payload, result.trace)


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_input_order_never_changes_the_outcome(case: str) -> None:
    """R-23 (DA-15): the payload, the trace and the snapshot digest ignore the order of the input."""
    document = read_json(CASES / case / "snapshot.json")
    expected = _outcome(case, document)
    for seed in range(10):
        assert _outcome(case, _shuffled(document, random.Random(seed))) == expected, f"seed {seed}"
