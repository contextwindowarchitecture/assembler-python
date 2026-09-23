"""Runs the vendored conformance cases and reports each outcome (conformance/README.md, Reporting
results). A harness around the pure core: it reads case files, and assemble() never does.

    uv run python -m cwa.conformance > conformance-report.json
"""
from __future__ import annotations

import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, Mapping

from . import assemble
from .render import REGISTRY as RENDERERS
from .snapshot import Snapshot, SnapshotError
from .strings import utf16
from .tokenize import REGISTRY as TOKENIZERS

# Trace fields that may differ between runs (R-23); everything else is compared.
IGNORED = ("trace_id", "timings")


def comparable(trace: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in trace.items() if key not in IGNORED}


def _first_difference(actual: Any, expected: Any, path: str = "") -> str | None:
    """The JSON pointer of the first place two documents differ, or None."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(actual.keys() | expected.keys(), key=utf16):
            if key not in actual or key not in expected:
                return f"{path}/{key}"
            if found := _first_difference(actual[key], expected[key], f"{path}/{key}"):
                return found
        return None
    if isinstance(actual, list) and isinstance(expected, list):
        for index, (a, e) in enumerate(zip(actual, expected)):
            if found := _first_difference(a, e, f"{path}/{index}"):
                return found
        return None if len(actual) == len(expected) else f"{path}/{min(len(actual), len(expected))}"
    return None if actual == expected else path or "/"


def run_case(directory: Path) -> dict[str, Any]:
    """One report entry: passed, failed with what differed, or skipped for a missing tokenizer or renderer."""
    meta = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    entry = {"id": meta["id"], "rules": meta["rules"]}
    document = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    for field, registry in (("tokenizer", TOKENIZERS), ("renderer", RENDERERS)):
        if isinstance(document, dict) and isinstance(document.get(field), str) and document[field] not in registry:
            return {**entry, "outcome": "skipped", "detail": f"no {field} {document[field]}"}
    try:
        result = assemble(Snapshot.from_json(document))
    except SnapshotError as error:
        return {**entry, "outcome": "failed", "detail": f"snapshot rejected: {'; '.join(error.problems)}"}
    except Exception as error:  # a crash is a failed case, not a failed run
        return {**entry, "outcome": "failed", "detail": f"{type(error).__name__}: {error}"}
    payload_file = directory / "expected.payload.txt"
    expected_payload = payload_file.read_bytes() if payload_file.exists() else None
    if result.payload != expected_payload:
        detail = ("refused, but a payload was expected" if result.payload is None else
                  "a payload, but a refusal was expected" if expected_payload is None else "payload bytes differ")
        return {**entry, "outcome": "failed", "detail": detail}
    expected_trace = json.loads((directory / "expected.trace.json").read_text(encoding="utf-8"))
    if where := _first_difference(comparable(result.trace), comparable(expected_trace)):
        return {**entry, "outcome": "failed", "detail": f"trace differs at {where}"}
    return {**entry, "outcome": "passed"}


def report(cases: Path, lock: Mapping[str, Any]) -> dict[str, Any]:
    """The conformance_report.schema.json document for every case under `cases`, by id."""
    return {
        "implementation": {"name": "cwa-assembler", "version": version("cwa-assembler"), "language": "python"},
        "contract": {"website_commit": lock["source"]["commit"], "dirty": lock["source"]["dirty"]},
        "cases": [run_case(d) for d in sorted((p for p in cases.iterdir() if p.is_dir()), key=lambda p: utf16(p.name))],
    }


def main(argv: list[str]) -> None:
    cases = Path(argv[0] if argv else "conformance/cases")
    lock = json.loads(Path(argv[1] if len(argv) > 1 else "contract.lock.json").read_text(encoding="utf-8"))
    sys.stdout.write(json.dumps(report(cases, lock), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
