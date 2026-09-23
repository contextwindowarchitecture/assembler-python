"""The conformance runner and its report (conformance/README.md, Reporting results; R-21)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cwa import contract
from cwa.conformance import report, run_case, run_rejection
from cwa.strings import utf16
from conftest import CASES, REJECTIONS, ROOT, read_json

LOCK = read_json(ROOT / "contract.lock.json")


@pytest.fixture
def case(tmp_path) -> Path:
    """A private copy of the three-slot case to break."""
    return Path(shutil.copytree(CASES / "fixture-three-slot", tmp_path / "fixture-three-slot"))


def edit(path: Path, change) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_a_matching_case_passes(case):
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "passed"}


def test_a_trace_that_differs_fails_and_names_the_field(case):
    edit(case / "expected.trace.json", lambda t: t["included"][0].update(tokens=99))
    outcome = run_case(case)
    assert outcome["outcome"] == "failed" and "included" in outcome["detail"]


def test_a_payload_that_differs_fails(case):
    (case / "expected.payload.txt").write_bytes(b"something else")
    assert run_case(case)["outcome"] == "failed"


def test_a_refusal_where_a_payload_was_expected_fails(case):
    (case / "expected.payload.txt").unlink()
    assert run_case(case)["outcome"] == "failed"


def test_a_snapshot_the_assembler_rejects_fails(case):
    edit(case / "snapshot.json", lambda s: s.update(assembly_time="yesterday"))
    outcome = run_case(case)
    assert outcome["outcome"] == "failed" and "assembly_time" in outcome["detail"]


@pytest.mark.parametrize("field", ["tokenizer", "renderer"])
def test_a_case_needing_a_tokenizer_or_renderer_it_lacks_is_skipped(case, field):
    edit(case / "snapshot.json", lambda s: s.update({field: "elsewhere/v9"}))
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "skipped",
                              "detail": f"no {field} elsewhere/v9"}


@pytest.fixture
def rejection(tmp_path) -> Path:
    """A private copy of a rejection case: its profile is for another route (R-17, R-20)."""
    return Path(shutil.copytree(REJECTIONS / "profile-route-mismatch", tmp_path / "profile-route-mismatch"))


def test_a_rejection_case_the_assembler_rejects_is_rejected(rejection):
    assert run_rejection(rejection) == {"id": "profile-route-mismatch", "rules": ["R-17", "R-20"], "outcome": "rejected"}


def test_a_rejection_case_that_assembles_fails(rejection):
    edit(rejection / "snapshot.json", lambda s: s["profile"].update(route="contract-fixture"))
    assert run_rejection(rejection) == {"id": "profile-route-mismatch", "rules": ["R-17", "R-20"], "outcome": "failed",
                                        "detail": "assembled a payload instead of rejecting the snapshot"}


def test_a_rejection_case_that_refuses_fails(rejection):
    def valid_but_refused(s):
        s["profile"]["route"] = "contract-fixture"
        next(b for b in s["batches"] if b["producer"]["id"] == "conversation")["items"].clear()
    edit(rejection / "snapshot.json", valid_but_refused)
    assert run_rejection(rejection)["detail"] == "refused with required_slot_missing instead of rejecting the snapshot"


def test_a_rejection_case_that_crashes_fails(rejection, monkeypatch):
    def crash(document, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr("cwa.conformance.Snapshot.from_json", crash)
    assert run_rejection(rejection)["detail"] == "RuntimeError: boom"


def test_a_rejection_case_needing_a_tokenizer_it_lacks_is_skipped(rejection):
    edit(rejection / "snapshot.json", lambda s: s.update(tokenizer="elsewhere/v9"))
    assert run_rejection(rejection)["outcome"] == "skipped"


def test_the_report_covers_every_case_in_id_order_and_names_the_vendored_commit():
    produced = report(CASES, LOCK)
    assert not contract.errors("conformance_report", produced)
    assert [c["id"] for c in produced["cases"]] == sorted((p.name for p in CASES.iterdir()), key=utf16)
    assert [c["id"] for c in produced["rejections"]] == sorted((p.name for p in REJECTIONS.iterdir()), key=utf16)
    assert {c["outcome"] for c in produced["rejections"]} == {"rejected"}
    assert produced["contract"] == {"website_commit": LOCK["source"]["commit"], "dirty": LOCK["source"]["dirty"]}
    assert produced["implementation"] == {"name": "cwa-assembler", "version": "0.0.1", "language": "python"}


def test_the_committed_report_is_current():
    """Regenerate with: uv run python -m cwa.conformance > conformance-report.json"""
    assert read_json(ROOT / "conformance-report.json") == report(CASES, LOCK)
