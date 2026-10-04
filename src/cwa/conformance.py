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
from .render import REGISTRY as RENDERERS, REQUIRED as REQUIRED_RENDERERS
from .snapshot import Snapshot, SnapshotError, UnsupportedComponentError
from .strings import utf16
from .tokenize import REGISTRY as TOKENIZERS

# Trace fields that may differ between runs (R-23), and recovery.detail, free text for people that no
# requirement defines (conformance/README.md, Running a case, step 4); everything else is compared.
IGNORED = ("trace_id", "timings")
IGNORED_IN_RECOVERY = ("detail",)
# The tokenizers and renderers every implementation provides (conformance/README.md, Tokenizers and renderers, before
# its Optional list); any other one is optional. tests/test_tokenize.py and tests/test_render.py pin them to the
# README's bullets: the built-in tokenizers, all of them required, and the required renderers. Copied, so the set stays
# the required one whatever a registry holds when a case runs.
REQUIRED = {"tokenizer": frozenset(TOKENIZERS), "renderer": frozenset(REQUIRED_RENDERERS)}


def comparable(trace: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of the trace without the fields conformance never compares; the trace is left as it is."""
    kept = {key: value for key, value in trace.items() if key not in IGNORED}
    if isinstance(recovery := kept.get("recovery"), Mapping):
        kept["recovery"] = {key: value for key, value in recovery.items() if key not in IGNORED_IN_RECOVERY}
    return kept


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


def _unprovided(lacking: list[tuple[str, str]]) -> dict[str, str] | None:
    """The outcome for the tokenizers and renderers, as (field, id), that a case uses and this implementation does not
    provide (conformance/README.md, Reporting results): skipped when any is optional, whichever it would check first,
    and failed when every one is required, since every implementation provides those. None when it lacks none."""
    if optional := [(field, name) for field, name in lacking if name not in REQUIRED[field]]:
        return {"outcome": "skipped", "detail": " and ".join(f"no {field} {name}" for field, name in optional)}
    if lacking:
        named = " and ".join(f"no {field} {name}" for field, name in lacking)
        return {"outcome": "failed", "detail": f"{named}, which every implementation provides"}
    return None


def run_case(directory: Path) -> dict[str, Any]:
    """One report entry: passed, failed with what differed, or skipped for an optional tokenizer or renderer this
    implementation does not provide. A case lacking only required ones has failed. Decided from every component the
    case names before it runs, since a snapshot stops on the first one it lacks."""
    meta = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    entry = {"id": meta["id"], "rules": meta["rules"]}
    document = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    provided = {"tokenizer": TOKENIZERS, "renderer": RENDERERS}
    lacking = [(field, name) for field in ("tokenizer", "renderer")
               if isinstance(document, dict) and isinstance(name := document.get(field), str) and name not in provided[field]]
    if unprovided := _unprovided(lacking):
        return {**entry, **unprovided}
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


def run_rejection(directory: Path) -> dict[str, Any]:
    """One rejections entry: rejected before assembly, failed with what happened instead, or skipped (R-17).

    Every check but the renderer's own runs before a renderer is needed, and no check needs a tokenizer, so the
    snapshot itself says whether a missing component matters. It is rejected for any other check it breaks, whatever
    it names. Stopping for a renderer this implementation lacks leaves the renderer's check as the one the case breaks:
    skipped when that renderer is optional, failed when it is required. Stopping for a tokenizer means it passed every
    check, so it has failed."""
    meta = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    entry = {"id": meta["id"], "rules": meta["rules"]}
    document = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    try:
        result = assemble(Snapshot.from_json(document))
    except SnapshotError:
        return {**entry, "outcome": "rejected"}
    except UnsupportedComponentError as error:
        if error.component == "renderer" and (unprovided := _unprovided([(error.component, error.id)])):
            return {**entry, **unprovided}
        return {**entry, "outcome": "failed",
                "detail": f"passed every check instead of rejecting the snapshot, then found no {error.component} {error.id}"}
    except Exception as error:  # a crash is not a rejection
        return {**entry, "outcome": "failed", "detail": f"{type(error).__name__}: {error}"}
    did = "assembled a payload" if not result.refused else f"refused with {result.trace['refused']['reason']}"
    return {**entry, "outcome": "failed", "detail": f"{did} instead of rejecting the snapshot"}

def _by_id(directory: Path) -> list[Path]:
    return sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: utf16(p.name))


def report(cases: Path, lock: Mapping[str, Any], rejections: Path | None = None) -> dict[str, Any]:
    """The conformance_report.schema.json document for every case under `cases` and every rejection case under
    `rejections` (by default the rejections folder beside `cases`), each by id."""
    rejections = rejections or cases.parent / "rejections"
    return {
        "implementation": {"name": "contextwindowarchitecture-assembler", "version": version("contextwindowarchitecture-assembler"), "language": "python"},
        "contract": {"website_commit": lock["source"]["commit"], "dirty": lock["source"]["dirty"]},
        "cases": [run_case(d) for d in _by_id(cases)],
        "rejections": [run_rejection(d) for d in _by_id(rejections)],
    }


def main(argv: list[str]) -> None:
    cases = Path(argv[0] if argv else "conformance/cases")
    lock = json.loads(Path(argv[1] if len(argv) > 1 else "contract.lock.json").read_text(encoding="utf-8"))
    sys.stdout.write(json.dumps(report(cases, lock), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
