"""assemble() reads nothing outside the snapshot: no network, no clock (R-18, R-23)."""
import datetime
import socket
import time

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def _forbidden(*args, **kwargs):
    raise AssertionError("assemble() reached outside its snapshot")


class _NoClock(datetime.datetime):
    now = utcnow = today = classmethod(_forbidden)


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_assemble_needs_no_network_or_clock(case, monkeypatch):
    snapshot = Snapshot.from_json(read_json(CASES / case / "snapshot.json"))
    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    for name in ("time", "time_ns", "monotonic", "perf_counter", "localtime", "gmtime"):
        monkeypatch.setattr(time, name, _forbidden)
    monkeypatch.setattr(datetime, "datetime", _NoClock)
    assert assemble(snapshot, trace_id="t").payload is not None
