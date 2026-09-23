from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "cases"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_snapshot() -> dict:
    """A fresh copy of the three-slot conformance snapshot document."""
    return copy.deepcopy(read_json(CASES / "fixture-three-slot" / "snapshot.json"))
