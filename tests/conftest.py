from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "cases"
REJECTIONS = ROOT / "conformance" / "rejections"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def published(verb: str) -> list[str]:
    """The ids conformance/README.md's Tokenizers and renderers section publishes, which every implementation
    provides: the bullets that count (verb "counts", the tokenizers) or render ("renders", the renderers)."""
    readme = (ROOT / "conformance" / "README.md").read_text(encoding="utf-8")
    section = readme.split("\n## Tokenizers and renderers\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(rf"^- `([^`]+)` {verb} ", section, flags=re.MULTILINE)


@pytest.fixture
def fixture_snapshot() -> dict:
    """A fresh copy of the three-slot conformance snapshot document."""
    return copy.deepcopy(read_json(CASES / "fixture-three-slot" / "snapshot.json"))
