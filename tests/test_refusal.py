"""Refusals: required slots (R-4), the refused-trace shape (R-17) and refusal precedence (R-21)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def items(snapshot: dict, producer: str) -> list[dict]:
    return next(b for b in snapshot["batches"] if b["producer"]["id"] == producer)["items"]


def output_contract(**fields) -> dict:
    item = {"id": "contract:json", "slot": "governance.output_contract", "source": "policy-registry", "source_version": "1",
            "authority": "governing", "trust": "verified", "freshness": "2026-09-22T11:00:00Z", "body": "Answer as JSON."}
    return {**item, **fields}


def parser_route(snapshot: dict) -> dict:
    snapshot["route_policy"]["parser"] = True
    snapshot["route_policy"]["producers"]["policy-registry"]["slots"].append("governance.output_contract")
    snapshot["profile"]["placement"].insert(1, {"slot": "governance.output_contract", "wrap": "xml:governance.output_contract"})
    return snapshot


def assert_refused(result, reason: str) -> None:
    assert result.refused
    assert result.payload is None
    assert result.trace["refused"] == {"bool": True, "reason": reason}
    assert result.trace["result"] is None
    assert result.trace["included"] == [] and result.trace["compressed"] == []


@pytest.mark.parametrize("producer, slot", [("policy-registry", "governance.instructions"), ("conversation", "interaction.query")])
def test_every_assembly_needs_instructions_and_a_query(fixture_snapshot, producer, slot):
    items(fixture_snapshot, producer).clear()
    assert_refused(assemble(Snapshot.from_json(fixture_snapshot)), "required_slot_missing")


def test_an_excluded_instruction_does_not_count_and_its_exclusion_stays_in_the_trace(fixture_snapshot):
    items(fixture_snapshot, "policy-registry")[0]["trust"] = "unverified"
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert_refused(result, "required_slot_missing")
    assert result.trace["excluded"][-1] == {
        "item_id": "policy:v12", "reason": "untrusted_in_governance", "stage": "assembler", "slot": "governance.instructions"}


def test_a_parser_route_also_needs_an_output_contract(fixture_snapshot):
    parser_route(fixture_snapshot)
    assert_refused(assemble(Snapshot.from_json(fixture_snapshot)), "required_slot_missing")
    items(fixture_snapshot, "policy-registry").append(output_contract())
    assert not assemble(Snapshot.from_json(fixture_snapshot)).refused


def test_other_routes_do_not_need_an_output_contract(fixture_snapshot):
    assert not assemble(Snapshot.from_json(fixture_snapshot)).refused


# R-17: protected content that cannot fit refuses rather than truncating, and nothing is shed first.

def test_protected_content_over_budget_refuses_without_shedding(fixture_snapshot):
    fixture_snapshot["budget"]["input"] = 20  # instructions and query alone render 21 tokens
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert_refused(result, "protected_content_over_budget")
    assert [row["reason"] for row in result.trace["excluded"]] == ["expired"]


def test_protected_content_that_exactly_fits_is_not_refused(fixture_snapshot):
    fixture_snapshot["budget"]["input"] = 21
    items(fixture_snapshot, "policy-corpus").clear()
    assert not assemble(Snapshot.from_json(fixture_snapshot)).refused


def test_a_missing_required_slot_is_reported_before_the_budget(fixture_snapshot):
    fixture_snapshot["budget"]["input"] = 1
    items(fixture_snapshot, "conversation").clear()
    assert_refused(assemble(Snapshot.from_json(fixture_snapshot)), "required_slot_missing")


def test_an_unresolved_conflict_is_reported_before_the_budget(fixture_snapshot):
    fixture_snapshot["budget"]["input"] = 1
    instructions = items(fixture_snapshot, "policy-registry")
    instructions.append({**instructions[0], "id": "policy:v13", "body": "Never refund."})
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "instruction", "items": ["policy:v12", "policy:v13"]}]
    assert_refused(assemble(Snapshot.from_json(fixture_snapshot)), "conflict_unresolved")


# R-12: a route that requires evidence never answers from nothing, and says how to recover.

def evidence_case(name: str) -> dict:
    return read_json(CASES / name / "snapshot.json")


def recovery(snapshot: dict) -> str | None:
    result = assemble(Snapshot.from_json(snapshot))
    if result.refused:
        assert_refused(result, "evidence_required")
        return result.trace["recovery"]["action"]
    assert "recovery" not in result.trace
    return None


def observation() -> dict:
    return {"id": "obs:order-42", "slot": "evidence.tool_results", "source": "crm", "source_version": "1", "authority": "observation",
            "trust": "unverified", "freshness": "2026-09-22T11:59:00Z", "body": "order 42: pro plan", "injection_risk": "untrusted_content"}


def test_no_admitted_evidence_asks_for_context():
    assert recovery(evidence_case("evidence-request-context")) == "request_context"


def test_routes_that_do_not_require_evidence_answer_without_it():
    snapshot = evidence_case("evidence-request-context")
    del snapshot["route_policy"]["requires_evidence"]
    assert recovery(snapshot) is None


def test_a_tool_result_is_evidence_too():
    snapshot = evidence_case("evidence-request-context")
    snapshot["batches"].append({"producer": {"id": "crm-mcp", "kind": "mcp"}, "items": [observation()], "excluded": []})
    assert recovery(snapshot) is None


def test_evidence_omitted_without_variants_asks_for_a_precomputed_summary():
    snapshot = evidence_case("evidence-precompute-summary")
    assert recovery(snapshot) == "precompute_summary"
    trace = assemble(Snapshot.from_json(snapshot)).trace
    assert [(row["item_id"], row["reason"]) for row in trace["excluded"]] == [("kb:c", "over_budget"), ("kb:b", "over_budget")]


def test_a_minimum_the_fitted_evidence_meets_is_not_refused():
    snapshot = evidence_case("evidence-precompute-summary")
    snapshot["route_policy"]["slots"]["evidence.knowledge"]["min_included"] = 1
    assert recovery(snapshot) is None


def test_evidence_whose_variants_did_not_fit_asks_for_narrower_retrieval():
    assert recovery(evidence_case("evidence-retrieve-narrower")) == "retrieve_narrower"


def test_the_minimum_counts_items_not_occurrences():
    snapshot = evidence_case("evidence-precompute-summary")
    snapshot["budget"]["input"] = 4096
    snapshot["route_policy"]["slots"]["evidence.knowledge"]["min_included"] = 4
    placement = snapshot["profile"]["placement"]
    placement.insert(-1, next(p for p in placement if p["slot"] == "evidence.knowledge"))
    assert recovery(snapshot) == "request_context"


def test_a_protected_refusal_comes_before_the_evidence_check():
    snapshot = evidence_case("evidence-request-context")
    snapshot["budget"]["input"] = 10
    assert_refused(assemble(Snapshot.from_json(snapshot)), "protected_content_over_budget")


def test_a_protected_item_over_its_own_cap_refuses_although_the_payload_fits(fixture_snapshot):
    items(fixture_snapshot, "policy-registry")[0]["token_budget"] = 8  # its body renders 9 tokens
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert_refused(result, "protected_content_over_budget")
    assert [row["reason"] for row in result.trace["excluded"]] == ["expired"]


def test_a_protected_item_exactly_at_its_cap_is_kept(fixture_snapshot):
    items(fixture_snapshot, "policy-registry")[0]["token_budget"] = 9
    assert not assemble(Snapshot.from_json(fixture_snapshot)).refused
