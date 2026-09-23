"""Admission: every candidate is admitted or excluded with exactly one registered reason."""
from __future__ import annotations

import copy

import pytest

from cwa import Snapshot, assemble

def knowledge(**fields) -> dict:
    item = {"id": "kb:x", "slot": "evidence.knowledge", "source": "policy-corpus", "source_version": "1",
            "authority": "reference_only", "trust": "verified", "freshness": "2026-09-12T15:30:00Z",
            "relevance": 0.9, "scope": {"tenant": "acme"}, "body": "A passage."}
    item.update(fields)
    return {k: v for k, v in item.items() if v is not None}


def batch(snapshot: dict, producer: str) -> dict:
    return next(b for b in snapshot["batches"] if b["producer"]["id"] == producer)


def add(snapshot: dict, producer: str, *items: dict) -> dict:
    batch(snapshot, producer)["items"].extend(copy.deepcopy(items))
    return snapshot


def exclusions(snapshot: dict) -> list[tuple[str, str]]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return [(row["item_id"], row["reason"]) for row in trace["excluded"] if row["stage"] == "assembler"]


# R-2: invalid structure is refused and recorded per item, never by rejecting the snapshot.

@pytest.mark.parametrize("fields, reason", [
    ({"body": None}, "missing_field:body"),
    ({"relevance": None}, "missing_field:relevance"),
    ({"slot": "evidence.web"}, "unknown_slot"),
    ({"authority": "reference"}, "unknown_authority"),
    ({"freshness": "2026-02-30T12:00:00Z"}, "invalid_structure"),
    ({"surprise": True}, "invalid_structure"),
    ({"body": None, "slot": "evidence.web"}, "missing_field:body"),
])
def test_schema_invalid_items_are_excluded_with_the_earliest_reason(fixture_snapshot, fields, reason):
    assert exclusions(add(fixture_snapshot, "policy-corpus", knowledge(**fields))) == [("kb:x", reason)]


def test_items_without_a_usable_id_are_recorded_by_producer_and_position(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(id=None, body="first"), knowledge(id="  ", body="second"), knowledge(id="kb:ok"))
    assert exclusions(fixture_snapshot) == [
        ("policy-corpus#invalid-0", "missing_field:id"),
        ("policy-corpus#invalid-1", "invalid_structure"),
    ]
    replayed = Snapshot.from_json(Snapshot.from_json(fixture_snapshot).to_json())
    assert [r["item_id"] for r in assemble(replayed).trace["excluded"] if r["stage"] == "assembler"] == [
        "policy-corpus#invalid-0", "policy-corpus#invalid-1"]


def test_excluded_items_never_reach_the_payload(fixture_snapshot):
    before = assemble(Snapshot.from_json(fixture_snapshot)).payload
    add(fixture_snapshot, "policy-corpus", knowledge(body=None), knowledge(id="kb:bad", slot="evidence.web"))
    assert assemble(Snapshot.from_json(fixture_snapshot)).payload == before


def add_batch(snapshot: dict, producer: str, kind: str, *items: dict) -> dict:
    snapshot["batches"].append({"producer": {"id": producer, "kind": kind}, "items": copy.deepcopy(list(items)), "excluded": []})
    return snapshot


def state_user(**fields) -> dict:
    item = {"id": "user:plan", "slot": "state.user", "source": "accounts-db", "source_version": "1", "authority": "state",
            "trust": "verified", "freshness": "2026-09-22T11:59:00Z", "scope": {"tenant": "acme"}, "body": "plan=pro"}
    item.update(fields)
    return {k: v for k, v in item.items() if v is not None}


# R-15, R-8: producer identity comes from the application and the route, never from item fields.

def test_producers_the_route_does_not_list_are_refused_before_structure(fixture_snapshot):
    add_batch(fixture_snapshot, "rogue", "retrieval", knowledge(id="rogue:1"), knowledge(id="rogue:2", body=None))
    assert exclusions(fixture_snapshot) == [("rogue:1", "producer_not_authenticated"), ("rogue:2", "producer_not_authenticated")]


def test_a_producer_whose_kind_differs_from_the_route_is_refused(fixture_snapshot):
    batch(fixture_snapshot, "policy-corpus")["producer"]["kind"] = "mcp"
    assert exclusions(fixture_snapshot) == [("refunds-eu:v17#p4", "producer_not_authenticated")]


def test_a_producer_may_only_emit_the_slots_the_route_grants(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", state_user())
    assert exclusions(fixture_snapshot) == [("user:plan", "producer_slot_not_allowed")]


def test_state_slots_only_accept_state_producers_even_if_the_route_lists_others(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"]["policy-corpus"]["slots"].append("state.user")
    add(fixture_snapshot, "policy-corpus", state_user())
    assert exclusions(fixture_snapshot) == [("user:plan", "producer_slot_not_allowed")]


# R-2: an id must identify one item in the payload and the trace.

def test_repeated_ids_exclude_every_copy(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(id="kb:dup", body="one"), knowledge(id="kb:dup", body="two"))
    assert exclusions(fixture_snapshot) == [("kb:dup", "duplicate_item_id"), ("kb:dup", "duplicate_item_id")]


def test_an_id_a_producer_already_reported_as_excluded_is_ambiguous(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(id="memory:expired"))
    assert exclusions(fixture_snapshot) == [("memory:expired", "duplicate_item_id")]


def test_ids_used_by_refused_candidates_still_count(fixture_snapshot):
    add_batch(fixture_snapshot, "rogue", "retrieval", knowledge(id="refunds-eu:v17#p4"))
    assert exclusions(fixture_snapshot) == [
        ("refunds-eu:v17#p4", "duplicate_item_id"),
        ("refunds-eu:v17#p4", "producer_not_authenticated"),
    ]


def place(snapshot: dict, *slots: str) -> dict:
    """Add placements so admitted items in these slots render."""
    snapshot["profile"]["placement"][-1:-1] = [{"slot": s, "wrap": "xml:" + s} for s in slots]
    return snapshot


def turn(id: str, slot: str = "interaction.history", **fields) -> dict:
    item = {"id": id, "slot": slot, "source": "conversation:c42", "source_version": "1", "authority": "user",
            "trust": "unverified", "freshness": "2026-09-22T11:59:00Z", "body": "Earlier turn."}
    item.update(fields)
    return item


def included(snapshot: dict) -> list[str]:
    return [row["item_id"] for row in assemble(Snapshot.from_json(snapshot)).trace["included"]]


# R-1, R-13, R-14: one authority role per slot; roles classify, they never rank facts.

@pytest.mark.parametrize("fields", [{"authority": "observation"}, {"authority": "untrusted"}, {"authority": "governing"}])
def test_retrieval_packets_carry_reference_only(fixture_snapshot, fields):
    assert exclusions(add(fixture_snapshot, "policy-corpus", knowledge(**fields))) == [("kb:x", "authority_not_allowed")]


def test_governance_items_cannot_be_untrusted(fixture_snapshot):
    policy = dict(batch(fixture_snapshot, "policy-registry")["items"][0], id="policy:v13", authority="untrusted")
    assert exclusions(add(fixture_snapshot, "policy-registry", policy)) == [("policy:v13", "authority_not_allowed")]


def test_other_slots_may_lower_to_untrusted(fixture_snapshot):
    place(fixture_snapshot, "interaction.history")
    add(fixture_snapshot, "conversation", turn("turn:17", authority="untrusted"))
    assert exclusions(fixture_snapshot) == []
    assert "turn:17" in included(fixture_snapshot)


def test_prior_model_turns_must_be_untrusted(fixture_snapshot):
    place(fixture_snapshot, "interaction.history")
    add(fixture_snapshot, "conversation", turn("turn:17a", lineage="generated"), turn("turn:17b", lineage="generated", authority="untrusted"))
    assert exclusions(fixture_snapshot) == [("turn:17a", "authority_not_allowed")]
    assert "turn:17b" in included(fixture_snapshot)


def tool(id: str, **fields) -> dict:
    item = {"id": id, "slot": "governance.capabilities", "source": "capability-policy:support-chat@v3", "source_version": "v3",
            "authority": "governing", "trust": "verified", "freshness": "2026-09-20T08:00:00Z", "injection_risk": "none",
            "body": f"{id.split(':')[-1]}(order_id: string)"}
    item.update(fields)
    return item


@pytest.fixture
def with_tools(fixture_snapshot) -> dict:
    fixture_snapshot["route_policy"]["producers"].update({
        "cap-policy": {"kind": "capability_policy", "slots": ["governance.capabilities"]},
        "crm-mcp": {"kind": "mcp", "slots": ["governance.capabilities"]},
    })
    fixture_snapshot["capabilities"] = {"policy_producer": "cap-policy", "allow_list_version": "v3", "allowed_ids": ["cap:issue_refund"]}
    return place(fixture_snapshot, "governance.capabilities")


# R-15: only the authenticated capability policy admits tools, and only those on its allow-list.

def test_the_capability_policy_admits_allowed_tools(with_tools):
    add_batch(with_tools, "cap-policy", "capability_policy", tool("cap:issue_refund"))
    assert exclusions(with_tools) == []
    assert "cap:issue_refund" in included(with_tools)


def test_tools_off_the_allow_list_are_refused(with_tools):
    add_batch(with_tools, "cap-policy", "capability_policy", tool("cap:delete_account"))
    assert exclusions(with_tools) == [("cap:delete_account", "capability_not_allowed")]


def test_an_adapter_cannot_place_a_tool_even_when_the_route_grants_it_the_slot(with_tools):
    add_batch(with_tools, "crm-mcp", "mcp", tool("cap:issue_refund", source="capability-policy:forged"))
    assert exclusions(with_tools) == [("cap:issue_refund", "capability_not_allowed")]


def test_without_a_capability_grant_no_tool_is_admitted(with_tools):
    del with_tools["capabilities"]
    add_batch(with_tools, "cap-policy", "capability_policy", tool("cap:issue_refund"))
    assert exclusions(with_tools) == [("cap:issue_refund", "capability_not_allowed")]


def instruction(**fields) -> dict:
    item = {"id": "policy:v13", "slot": "governance.instructions", "source": "policy-registry", "source_version": "v13",
            "authority": "governing", "trust": "verified", "freshness": "2026-09-01T00:00:00Z", "injection_risk": "none",
            "body": "Answer only from evidence."}
    item.update(fields)
    return item


def observation(id: str, **fields) -> dict:
    item = {"id": id, "slot": "evidence.tool_results", "source": "tool-call:77", "source_version": "1", "authority": "observation",
            "trust": "unverified", "freshness": "2026-09-22T11:59:50Z", "body": "order 42: pro plan"}
    item.update(fields)
    return item


# R-10, R-15: untrusted content is marked, and never governs.

@pytest.mark.parametrize("fields", [{"trust": "unverified"}, {"trust": "untrusted"}, {"injection_risk": "untrusted_content"}])
def test_governance_requires_verified_unmarked_content(fixture_snapshot, fields):
    assert exclusions(add(fixture_snapshot, "policy-registry", instruction(**fields))) == [("policy:v13", "untrusted_in_governance")]


def test_retrieved_and_user_content_must_stay_marked(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(injection_risk="none"))
    add(fixture_snapshot, "conversation", turn("turn:19", slot="interaction.query", injection_risk="none"))
    assert exclusions(fixture_snapshot) == [("turn:19", "untrusted_content_unmarked"), ("kb:x", "untrusted_content_unmarked")]


def test_only_a_route_verified_mcp_server_may_leave_output_unmarked(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"].update({
        "crm-mcp": {"kind": "mcp", "slots": ["evidence.tool_results"]},
        "docs-mcp": {"kind": "mcp", "slots": ["evidence.tool_results"], "verified": True},
    })
    place(fixture_snapshot, "evidence.tool_results")
    add_batch(fixture_snapshot, "crm-mcp", "mcp", observation("obs:crm", injection_risk="none"))
    add_batch(fixture_snapshot, "docs-mcp", "mcp", observation("obs:docs", injection_risk="none"))
    assert exclusions(fixture_snapshot) == [("obs:crm", "untrusted_content_unmarked")]
    assert "obs:docs" in included(fixture_snapshot)
