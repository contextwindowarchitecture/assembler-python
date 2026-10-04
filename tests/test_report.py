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
from conftest import CASES, REJECTIONS, ROOT, published, read_json, required

LOCK = read_json(ROOT / "contract.lock.json")
# Every implementation provides these (conformance/README.md, Tokenizers and renderers, before its Optional list); any
# other one is optional.
REQUIRED = [("tokenizer", name) for name in required("counts")] + [("renderer", name) for name in required("renders")]


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


# Optional ones: unpublished, and those the README's Optional list publishes, which every implementation may leave out.
OPTIONAL = [("tokenizer", "elsewhere/v9"), ("renderer", "elsewhere/v9")]
PUBLISHED_OPTIONAL = [(field, name) for field, verb in (("tokenizer", "counts"), ("renderer", "renders"))
                      for name in published(verb) if name not in required(verb)]


@pytest.mark.parametrize("field, name", OPTIONAL + PUBLISHED_OPTIONAL)
def test_a_case_needing_an_optional_tokenizer_or_renderer_it_lacks_is_skipped(case, monkeypatch, field, name):
    edit(case / "snapshot.json", lambda s: s.update({field: name}))
    if name in {"tokenizer": TOKENIZERS, "renderer": RENDERERS}[field]:
        lacking(monkeypatch, field, name)
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "skipped",
                              "detail": f"no {field} {name}"}


@pytest.mark.parametrize("field, name", REQUIRED)
def test_a_case_needing_a_required_tokenizer_or_renderer_it_lacks_fails(case, monkeypatch, field, name):
    """A case that uses only required ones is never skipped: an implementation that lacks one has failed it, and the
    detail names what it lacks. Nothing published reaches this, since this assembler provides all four."""
    edit(case / "snapshot.json", lambda s: s.update({field: name}))
    lacking(monkeypatch, field, name)
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "failed",
                              "detail": f"no {field} {name}, which every implementation provides"}


MIXED = [*[(("tokenizer", name), ("renderer", "elsewhere/v9")) for name in required("counts")],
         *[(("renderer", name), ("tokenizer", "elsewhere/v9")) for name in required("renders")]]


@pytest.mark.parametrize("required, optional", MIXED, ids=[f"{r[1]}+optional-{o[0]}" for r, o in MIXED])
def test_a_case_lacking_an_optional_component_is_skipped_whatever_required_one_it_also_lacks(case, monkeypatch, required,
                                                                                              optional):
    """Reporting results: a case that uses an optional component the implementation lacks is skipped, whichever one it
    checks first. Only a case whose every missing component is required has failed."""
    edit(case / "snapshot.json", lambda s: s.update(dict([required, optional])))
    lacking(monkeypatch, *required)
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "skipped",
                              "detail": f"no {optional[0]} {optional[1]}"}


@pytest.mark.parametrize("renderer", required("renders"))
@pytest.mark.parametrize("tokenizer", required("counts"))
def test_a_case_lacking_only_required_components_fails_and_names_each(case, monkeypatch, tokenizer, renderer):
    edit(case / "snapshot.json", lambda s: s.update(tokenizer=tokenizer, renderer=renderer))
    lacking(monkeypatch, "tokenizer", tokenizer)
    lacking(monkeypatch, "renderer", renderer)
    assert run_case(case) == {"id": "fixture-three-slot", "rules": read_json(case / "case.json")["rules"], "outcome": "failed",
                              "detail": f"no tokenizer {tokenizer} and no renderer {renderer}, which every implementation provides"}


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


# profile-route-mismatch breaks a route check, which needs no renderer; profile-unrealizable breaks fixture-xml/v1's own.
@pytest.mark.parametrize("name, field, component, outcome", [
    *[("profile-route-mismatch", field, component, {"outcome": "rejected"}) for field, component in OPTIONAL + REQUIRED],
    *[("profile-unrealizable", field, component, {"outcome": "skipped", "detail": f"no renderer {component}"})
      for field, component in OPTIONAL + PUBLISHED_OPTIONAL if field == "renderer"],
    *[("profile-unrealizable", field, component,
       {"outcome": "failed", "detail": f"no renderer {component}, which every implementation provides"})
      for field, component in REQUIRED if field == "renderer"],
    *[("profile-unrealizable", field, component, {"outcome": "rejected"})
      for field, component in OPTIONAL + REQUIRED if field == "tokenizer"],
])
def test_a_rejection_case_is_skipped_only_for_an_optional_renderer_whose_check_it_breaks(tmp_path, monkeypatch, name,
                                                                                         field, component, outcome):
    """R-17 (conformance/README.md, Reporting results): every check but the renderer's own runs before a renderer is
    needed, and no check needs a tokenizer. So a rejection case that breaks another check is rejected, whatever it
    names. Only one that breaks the renderer's check can be kept from running, by a renderer the implementation
    lacks: skipped when that renderer is optional, and failed when it is required."""
    directory = Path(shutil.copytree(REJECTIONS / name, tmp_path / name))
    edit(directory / "snapshot.json", lambda s: s.update({field: component}))
    if component in {"tokenizer": TOKENIZERS, "renderer": RENDERERS}[field]:
        lacking(monkeypatch, field, component)
    assert run_rejection(directory) == {"id": name, "rules": read_json(directory / "case.json")["rules"], **outcome}


@pytest.mark.parametrize("name", [OPTIONAL[0][1], *published("counts")])
def test_a_rejection_case_that_passes_every_check_and_then_lacks_its_tokenizer_fails(rejection, monkeypatch, name):
    """R-17: no check needs a tokenizer, so a snapshot that stops for one has passed every check, where it should have
    been rejected. That holds for an optional tokenizer and a required one alike."""
    def valid(s):
        s["profile"]["route"] = "contract-fixture"
        s["tokenizer"] = name
    edit(rejection / "snapshot.json", valid)
    if name in TOKENIZERS:
        lacking(monkeypatch, "tokenizer", name)
    assert run_rejection(rejection) == {"id": "profile-route-mismatch", "rules": ["R-17", "R-20"], "outcome": "failed",
                                        "detail": f"passed every check instead of rejecting the snapshot, then found no tokenizer {name}"}


def test_the_report_covers_every_case_in_id_order_and_names_the_vendored_commit():
    produced = report(CASES, LOCK)
    assert not contract.errors("conformance_report", produced)
    assert [c["id"] for c in produced["cases"]] == sorted((p.name for p in CASES.iterdir()), key=utf16)
    assert [c["id"] for c in produced["rejections"]] == sorted((p.name for p in REJECTIONS.iterdir()), key=utf16)
    # Every rejection case is rejected, or skipped for a published optional renderer this assembler lacks.
    lacked = {f"no renderer {name}" for field, name in PUBLISHED_OPTIONAL if field == "renderer" and name not in RENDERERS}
    assert all(c["outcome"] == "rejected" or (c["outcome"] == "skipped" and c["detail"] in lacked)
               for c in produced["rejections"])
    assert produced["contract"] == {"website_commit": LOCK["source"]["commit"], "dirty": LOCK["source"]["dirty"]}
    assert produced["implementation"] == {"name": "contextwindowarchitecture-assembler", "version": "0.0.1", "language": "python"}


def test_the_committed_report_is_current():
    """Regenerate with: uv run python -m cwa.conformance > conformance-report.json"""
    assert read_json(ROOT / "conformance-report.json") == report(CASES, LOCK)
