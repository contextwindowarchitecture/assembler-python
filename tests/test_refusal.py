"""Refusals: required slots (R-4), the refused-trace shape (R-17) and refusal precedence (R-21)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble


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
