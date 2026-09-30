"""The conformance runner and its report (conformance/README.md, Reporting results; R-21)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cwa import contract
from cwa.conformance import comparable, report, run_case, run_rejection
from cwa.render import REGISTRY as RENDERERS
from cwa.strings import utf16
from cwa.tokenize import REGISTRY as TOKENIZERS
from conftest import CASES, REJECTIONS, ROOT, published, read_json

LOCK = read_json(ROOT / "contract.lock.json")
# Every implementation provides these (conformance/README.md, Tokenizers and renderers); any other one is optional.
REQUIRED = [("tokenizer", name) for name in published("counts")] + [("renderer", name) for name in published("renders")]


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


# conformance/README.md, Running a case, step 4: recovery.detail is free text for people that no
# requirement defines, so it is removed before traces are compared; the rest of recovery is not.

@pytest.fixture
def refusal(tmp_path) -> Path:
    """A private copy of a case that refuses with a recovery action (R-12)."""
    return Path(shutil.copytree(CASES / "evidence-request-context", tmp_path / "evidence-request-context"))


def test_an_expected_recovery_detail_is_not_compared(refusal):
    edit(refusal / "expected.trace.json", lambda t: t["recovery"].update(detail="Ask which order the refund is for."))
    assert run_case(refusal)["outcome"] == "passed"


def test_a_changed_recovery_action_still_fails(refusal):
    edit(refusal / "expected.trace.json", lambda t: t["recovery"].update(action="retrieve_narrower", detail="Anything."))
    assert run_case(refusal) == {"id": "evidence-request-context", "rules": read_json(refusal / "case.json")["rules"],
                                 "outcome": "failed", "detail": "trace differs at /recovery/action"}


def test_comparable_drops_recovery_detail_from_either_trace_and_leaves_the_trace_intact():
    trace = {"trace_id": "t", "timings": {"admission_ms": 1}, "refused": {"refused": True, "reason": "evidence_required"},
             "recovery": {"action": "request_context", "detail": "Why."}}
    assert comparable(trace) == {"refused": {"refused": True, "reason": "evidence_required"}, "recovery": {"action": "request_context"}}
    assert trace["recovery"] == {"action": "request_context", "detail": "Why."}
    assert comparable({"recovery": None}) == {"recovery": None}


def lacking(monkeypatch, field: str, name: str) -> None:
    """This implementation made to lack a tokenizer or renderer it builds in, until the test ends."""
    monkeypatch.delitem({"tokenizer": TOKENIZERS, "renderer": RENDERERS}[field], name)


@pytest.mark.parametrize("field", ["tokenizer", "renderer"])
def test_a_case_needing_an_optional_tokenizer_or_renderer_it_lacks_is_skipped(case, field):
    edit(case / "snapshot.json", lambda s: s.update({field: "elsewhere/v9"}))
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "skipped",
                              "detail": f"no {field} elsewhere/v9"}


@pytest.mark.parametrize("field, name", REQUIRED)
def test_a_case_needing_a_required_tokenizer_or_renderer_it_lacks_fails(case, monkeypatch, field, name):
    """A case that uses only required ones is never skipped: an implementation that lacks one has failed it, and the
    detail names what it lacks. Nothing published reaches this, since this assembler provides all four."""
    edit(case / "snapshot.json", lambda s: s.update({field: name}))
    lacking(monkeypatch, field, name)
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "failed",
                              "detail": f"no {field} {name}, which every implementation provides"}


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


@pytest.mark.parametrize("field, name, outcome", [
    ("renderer", "elsewhere/v9", {"outcome": "skipped", "detail": "no renderer elsewhere/v9"}),
    *[(field, name, {"outcome": "failed", "detail": f"no renderer {name}, which every implementation provides"})
      for field, name in REQUIRED if field == "renderer"],
    ("tokenizer", "elsewhere/v9", {"outcome": "rejected"}),
    *[(field, name, {"outcome": "rejected"}) for field, name in REQUIRED if field == "tokenizer"],
])
def test_only_a_renderer_it_lacks_keeps_a_rejection_case_from_running(rejection, monkeypatch, field, name, outcome):
    """R-17: a rejection case is skipped only for an optional renderer the implementation lacks, and one that lacks a
    required renderer has failed it. No snapshot check needs a tokenizer, so a tokenizer it lacks, optional or
    required, skips nothing: the case runs, and this one is rejected for the check it breaks."""
    edit(rejection / "snapshot.json", lambda s: s.update({field: name}))
    if name in {"tokenizer": TOKENIZERS, "renderer": RENDERERS}[field]:
        lacking(monkeypatch, field, name)
    assert run_rejection(rejection) == {"id": "profile-route-mismatch", "rules": ["R-17", "R-20"], **outcome}


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
