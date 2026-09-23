"""A stored snapshot replays to the same outcome in a fresh process, whatever its hash seed, time
zone or locale (R-23, §6 of docs/DESIGN.md)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json
from test_conformance import PENDING

REPLAY = """
import json, locale, sys
try:
    locale.setlocale(locale.LC_ALL, "")  # take the process locale from the environment, as an application might
except locale.Error:
    sys.exit(3)
from cwa import Snapshot, assemble
out = {}
for name, document in json.load(sys.stdin).items():
    snapshot = Snapshot.from_json(document)
    result = assemble(snapshot, trace_id="t")
    out[name] = {"payload": result.payload.hex() if result.payload is not None else None, "trace": result.trace, "digest": snapshot.digest()}
json.dump(out, sys.stdout)
"""

ENVIRONMENTS = [
    {"PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C"},
    {"PYTHONHASHSEED": "4242", "TZ": "Pacific/Kiritimati", "LC_ALL": "tr_TR.UTF-8"},
    {"PYTHONHASHSEED": "random", "TZ": "America/St_Johns", "LC_ALL": "de_DE.UTF-8"},
]


def _stored() -> dict[str, dict]:
    """Every case's snapshot as an application would store it: normalized, then written as JSON.
    Pending cases have no settled outcome to replay."""
    return {case.name: Snapshot.from_json(read_json(case / "snapshot.json")).to_json()
            for case in sorted(CASES.iterdir()) if case.name not in PENDING}


def _here(stored: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for name, document in stored.items():
        snapshot = Snapshot.from_json(document)
        result = assemble(snapshot, trace_id="t")
        out[name] = {"payload": result.payload.hex() if result.payload is not None else None, "trace": result.trace, "digest": snapshot.digest()}
    return out


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=lambda e: f"{e['TZ']}-{e['LC_ALL']}")
def test_a_stored_snapshot_replays_identically_in_a_fresh_process(environment):
    stored = _stored()
    replayed = subprocess.run([sys.executable, "-c", REPLAY], input=json.dumps(stored), capture_output=True, text=True,
                              env={**os.environ, **environment})
    if replayed.returncode == 3:
        pytest.skip(f"locale {environment['LC_ALL']} is not installed")
    assert replayed.returncode == 0, replayed.stderr
    assert json.loads(replayed.stdout) == json.loads(json.dumps(_here(stored)))
