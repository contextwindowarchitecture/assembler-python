"""assemble() reads nothing outside the snapshot: no network, no clock (R-18, R-23)."""
import datetime
import socket
import time

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json
from test_conformance import GAPS, PENDING


def _forbidden(*args, **kwargs):
    raise AssertionError("assemble() reached outside its snapshot")


class _NoClock(datetime.datetime):
    now = utcnow = today = classmethod(_forbidden)


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_assemble_needs_no_network_or_clock(case, monkeypatch):
    try:
        snapshot = Snapshot.from_json(read_json(CASES / case / "snapshot.json"))
    except GAPS:
        if case not in PENDING:
            raise
        return  # a pending case whose renderer or tokenizer does not exist yet
    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    for name in ("time", "time_ns", "monotonic", "perf_counter", "localtime", "gmtime"):
        monkeypatch.setattr(time, name, _forbidden)
    monkeypatch.setattr(datetime, "datetime", _NoClock)
    if case not in PENDING:
        assemble(snapshot, trace_id="t")
        return
    try:
        assemble(snapshot, trace_id="t")
    except GAPS:
        pass  # a pending case's milestone gap, not a read outside the snapshot
