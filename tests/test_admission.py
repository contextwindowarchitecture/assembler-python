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
    ({"slot": None}, "missing_field:slot"),
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


# R-22: an assembler exclusion row names the candidate's slot whenever the candidate names a real one.

def test_assembler_exclusion_rows_carry_the_slot_the_candidate_names(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(id="kb:no-body", body=None), knowledge(id="kb:web", slot="evidence.web"),
        knowledge(id="kb:odd", slot=["evidence.knowledge"]))
    add_batch(fixture_snapshot, "rogue", "retrieval", knowledge(id="rogue:1"))
    rows = assemble(Snapshot.from_json(fixture_snapshot)).trace["excluded"]
    assert [(row["item_id"], row.get("slot")) for row in rows] == [
        ("memory:expired", None),
        ("kb:no-body", "evidence.knowledge"), ("kb:odd", None), ("kb:web", None),
        ("rogue:1", "evidence.knowledge"),
    ]


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


# R-13, R-14, R-15: a producer's kind limits its slots, whatever the route lists.

def test_a_retrieval_producer_emits_only_evidence_slots_whatever_the_route_lists(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"]["policy-corpus"]["slots"] += ["governance.examples", "evidence.tool_results"]
    place(fixture_snapshot, "governance.examples", "evidence.tool_results")
    add(fixture_snapshot, "policy-corpus",
        knowledge(id="kb:example", slot="governance.examples", authority="governing", injection_risk="none"),
        knowledge(id="kb:obs", slot="evidence.tool_results", authority="observation"))
    assert exclusions(fixture_snapshot) == [("kb:example", "producer_slot_not_allowed")]
    assert "kb:obs" in included(fixture_snapshot)


def test_a_memory_producer_emits_only_memory_whatever_the_route_lists(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"]["memory-svc"]["slots"].append("interaction.history")
    place(fixture_snapshot, "interaction.history")
    add(fixture_snapshot, "memory-svc", turn("m:turn", source="turn:16"))
    assert exclusions(fixture_snapshot) == [("m:turn", "producer_slot_not_allowed")]


def test_an_mcp_producer_emits_only_evidence_slots_whatever_the_route_lists(fixture_snapshot):
    """A tool specification it sends to governance.capabilities falls to the capability check instead (with_tools below)."""
    fixture_snapshot["route_policy"]["producers"]["docs-mcp"] = {"kind": "mcp", "slots": ["evidence.tool_results", "governance.instructions"], "verified": True}
    place(fixture_snapshot, "evidence.tool_results")
    add_batch(fixture_snapshot, "docs-mcp", "mcp", observation("obs:docs"), instruction(id="docs:policy", source="docs-mcp"))
    assert exclusions(fixture_snapshot) == [("docs:policy", "producer_slot_not_allowed")]
    assert "obs:docs" in included(fixture_snapshot)


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


@pytest.mark.parametrize("invalid_body, valid_body", [("a", "b"), ("b", "a")])
def test_copies_of_an_id_order_by_their_rfc_8785_bytes(fixture_snapshot, invalid_body, valid_body):
    # R-23: rows for candidates sharing an id order by their RFC 8785 bytes, whatever the input order
    # (conformance/README.md, Ordering). Here the body decides, since it is the first key the copies differ in.
    invalid, valid = knowledge(id="kb:dup", body=invalid_body, relevance=None), knowledge(id="kb:dup", body=valid_body)
    rows = {invalid_body: ("kb:dup", "missing_field:relevance"), valid_body: ("kb:dup", "duplicate_item_id")}
    assert exclusions(add(fixture_snapshot, "policy-corpus", invalid, valid)) == [rows["a"], rows["b"]]


def producer_rows(snapshot: dict) -> list[tuple[str, str]]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return [(row["item_id"], row["reason"]) for row in trace["excluded"] if row["stage"] == "producer"]


def test_producer_rows_from_an_unauthenticated_batch_reach_the_trace(fixture_snapshot):
    # R-9: producer rows carry no content, so they reach the trace whether or not the route admits the producer.
    add_batch(fixture_snapshot, "rogue", "retrieval", knowledge(id="rogue:1"))["batches"][-1]["excluded"] = [
        {"item_id": "rogue:0", "reason": "below_threshold", "stage": "producer"}]
    assert ("rogue:0", "below_threshold") in producer_rows(fixture_snapshot)


def test_producer_rows_sharing_an_item_id_order_by_their_rfc_8785_bytes(fixture_snapshot):
    # R-23 (conformance/README.md, Ordering): supplied expired first, they trace below_threshold first.
    batch(fixture_snapshot, "policy-corpus")["excluded"] = [
        {"item_id": "kb:gone", "reason": "expired", "stage": "producer"},
        {"item_id": "kb:gone", "reason": "below_threshold", "stage": "producer"}]
    assert [row for row in producer_rows(fixture_snapshot) if row[0] == "kb:gone"] == [
        ("kb:gone", "below_threshold"), ("kb:gone", "expired")]


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


def test_the_query_and_state_never_carry_untrusted(fixture_snapshot):
    """R-1: the live query always carries user, and state is application-written (R-8)."""
    fixture_snapshot["route_policy"]["producers"]["state-svc"] = {"kind": "state", "slots": ["state.user"]}
    place(fixture_snapshot, "state.user")
    add_batch(fixture_snapshot, "state-svc", "state", state_user(authority="untrusted"))
    add(fixture_snapshot, "conversation", turn("turn:19u", slot="interaction.query", authority="untrusted"))
    assert exclusions(fixture_snapshot) == [("turn:19u", "authority_not_allowed"), ("user:plan", "authority_not_allowed")]


def test_tool_results_memory_and_history_may_carry_untrusted(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"]["crm-mcp"] = {"kind": "mcp", "slots": ["evidence.tool_results"]}
    place(fixture_snapshot, "evidence.tool_results", "interaction.memory", "interaction.history")
    add_batch(fixture_snapshot, "crm-mcp", "mcp", observation("obs:u", authority="untrusted"))
    add(fixture_snapshot, "memory-svc", memory(authority="untrusted"))
    add(fixture_snapshot, "conversation", turn("turn:16", authority="untrusted"))
    assert exclusions(fixture_snapshot) == []
    assert {"obs:u", "m:1", "turn:16"} <= set(included(fixture_snapshot))


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


def test_the_grants_producer_must_be_listed_with_kind_capability_policy(with_tools):
    # R-15: the route capability policy is the grant's producer listed with kind capability_policy; the same producer
    # listed with another kind cannot emit tools, although the grant names it and the allow-list names the tool.
    with_tools["route_policy"]["producers"]["cap-policy"]["kind"] = "policy"
    add_batch(with_tools, "cap-policy", "policy", tool("cap:issue_refund"))
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


# R-16: protection is a floor items cannot lower, and a ceiling only the route can raise.

def test_items_cannot_downgrade_a_protected_slot(fixture_snapshot):
    assert exclusions(add(fixture_snapshot, "policy-registry", instruction(tier="droppable"))) == [("policy:v13", "protected_tier_changed")]


def test_items_cannot_protect_themselves(fixture_snapshot):
    assert exclusions(add(fixture_snapshot, "policy-corpus", knowledge(tier="protected"))) == [("kb:x", "tier_upgrade_not_allowed")]


def test_the_route_can_raise_a_tier_and_items_may_then_claim_it(fixture_snapshot):
    fixture_snapshot["route_policy"]["tier_upgrades"] = {"evidence.knowledge": "protected"}
    add(fixture_snapshot, "policy-corpus", knowledge(tier="protected"))
    assert exclusions(fixture_snapshot) == []


def test_in_a_slot_the_route_raised_an_item_may_lower_its_own_tier(fixture_snapshot):
    # protected_tier_changed guards only slots protected by default (conformance/README.md).
    fixture_snapshot["route_policy"]["tier_upgrades"] = {"evidence.knowledge": "protected"}
    add(fixture_snapshot, "policy-corpus", knowledge(tier="droppable"))
    assert exclusions(fixture_snapshot) == []


def test_items_may_volunteer_a_lower_non_protected_tier(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(tier="droppable"))
    assert exclusions(fixture_snapshot) == []


def variant(id: str) -> dict:
    return {"id": id, "body": "Short.", "method": "extract", "lineage": "extracted"}


# R-18: each variant has its own id, so the trace can name the parent and the selected variant.

@pytest.mark.parametrize("variants", [[variant("kb:x")], [variant("kb:x/short"), variant("kb:x/short")]])
def test_variant_ids_must_differ_from_the_parent_and_each_other(fixture_snapshot, variants):
    assert exclusions(add(fixture_snapshot, "policy-corpus", knowledge(variants=variants))) == [("kb:x", "duplicate_variant_id")]


@pytest.mark.parametrize("field", ["id", "body", "method", "lineage"])
def test_a_variant_missing_one_of_its_fields_is_invalid_structure(fixture_snapshot, field):
    # R-2, R-21: missing_field:<name> names the item's own fields only (conformance/README.md).
    broken = {k: v for k, v in variant("kb:x/short").items() if k != field}
    assert exclusions(add(fixture_snapshot, "policy-corpus", knowledge(variants=[broken]))) == [("kb:x", "invalid_structure")]


def test_distinct_variant_ids_are_admitted(fixture_snapshot):
    add(fixture_snapshot, "policy-corpus", knowledge(variants=[variant("kb:x/short"), variant("kb:x/shorter")]))
    assert exclusions(fixture_snapshot) == []


def memory(**fields) -> dict:
    item = {"id": "m:1", "slot": "interaction.memory", "source": "turn:14", "source_version": "1", "authority": "generated",
            "trust": "unverified", "freshness": "2026-09-20T10:00:00Z", "expires": "2026-12-01T00:00:00Z", "body": "Prefers email."}
    item.update(fields)
    return item


# R-9, R-2, R-23: lifetime is judged against the snapshot's assembly_time at full precision.

@pytest.mark.parametrize("fields, reason", [
    ({"revoked_by": "turn:17"}, "revoked"),
    ({"expires": "2026-09-22T12:00:00.000Z"}, "expired"),
    ({"expires": "2026-09-22T14:00:00+02:00"}, "expired"),
    ({"expires": "2026-09-22T11:59:59.999999999Z"}, "expired"),
    ({"expires": "2026-09-22T12:00:00.0005Z"}, None),
    ({"freshness": "2026-09-22T12:00:00.000001Z"}, "future_freshness"),
    ({"freshness": "2026-09-22T12:00:00Z"}, None),
])
def test_lifetime_boundaries(fixture_snapshot, fields, reason):
    add(fixture_snapshot, "policy-corpus", knowledge(**fields))
    assert exclusions(fixture_snapshot) == ([("kb:x", reason)] if reason else [])


@pytest.mark.parametrize("freshness, reason", [
    ("2026-09-22T12:00:05Z", None),
    ("2026-09-22T12:00:05.000001Z", "future_freshness"),
])
def test_route_clock_skew_tolerance(fixture_snapshot, freshness, reason):
    fixture_snapshot["route_policy"]["clock_skew_seconds"] = 5
    add(fixture_snapshot, "policy-corpus", knowledge(freshness=freshness))
    assert exclusions(fixture_snapshot) == ([("kb:x", reason)] if reason else [])


def test_expired_memory_a_producer_failed_to_suppress_is_still_excluded(fixture_snapshot):
    add(fixture_snapshot, "memory-svc", memory(expires="2026-09-01T00:00:00Z"))
    assert exclusions(fixture_snapshot) == [("m:1", "expired")]


def task(**fields) -> dict:
    item = {"id": "task:8821", "slot": "state.task", "source": "workflow-db", "source_version": "1", "authority": "state",
            "trust": "verified", "freshness": "2026-09-22T11:59:00Z", "body": "refund_request: verify_eligibility=done"}
    item.update(fields)
    return item


# R-8: state is current at assembly time. R-9: memory names its source turn.

@pytest.mark.parametrize("freshness, reason", [("2026-09-22T11:59:00Z", None), ("2026-09-22T11:58:59.999Z", "stale_state")])
def test_state_older_than_the_route_allows_is_stale(fixture_snapshot, freshness, reason):
    fixture_snapshot["route_policy"]["producers"]["workflow"] = {"kind": "state", "slots": ["state.task"]}
    fixture_snapshot["route_policy"]["slots"] = {"state.task": {"max_age_seconds": 60}}
    place(fixture_snapshot, "state.task")
    add_batch(fixture_snapshot, "workflow", "state", task(freshness=freshness))
    assert exclusions(fixture_snapshot) == ([("task:8821", reason)] if reason else [])


@pytest.mark.parametrize("source, reason", [("turn:14", None), ("summary-job:3", "source_invalid")])
def test_memory_sources_must_name_their_turn(fixture_snapshot, source, reason):
    fixture_snapshot["route_policy"]["slots"] = {"interaction.memory": {"source_prefix": "turn:"}}
    place(fixture_snapshot, "interaction.memory")
    add(fixture_snapshot, "memory-svc", memory(source=source))
    assert exclusions(fixture_snapshot) == ([("m:1", reason)] if reason else [])


# R-2: scope keeps items inside their tenant, user and session. A missing key is not a wildcard.

@pytest.mark.parametrize("scope, reason", [
    ({"tenant": "acme"}, None),
    ({"tenant": "acme", "task": "refund_request"}, None),
    (None, "out_of_scope"),
    ({"task": "refund_request"}, "out_of_scope"),
    ({"tenant": "globex"}, "out_of_scope"),
    ({"tenant": "acme", "user": "u_12"}, "out_of_scope"),
])
def test_scope_must_match_and_required_keys_must_be_present(fixture_snapshot, scope, reason):
    fixture_snapshot["route_policy"]["slots"] = {"evidence.knowledge": {"required_scope": ["tenant"]}}
    add(fixture_snapshot, "policy-corpus", knowledge(scope=scope))
    assert exclusions(fixture_snapshot) == ([("kb:x", reason)] if reason else [])


# R-13, R-3: the route's versioned threshold and eligibility predicate, not the item's own description.

@pytest.fixture
def with_eligibility(fixture_snapshot) -> dict:
    fixture_snapshot["route_policy"]["slots"] = {"evidence.knowledge": {"min_relevance": 0.8, "max_age_seconds": 7776000}}
    return fixture_snapshot


@pytest.mark.parametrize("fields, reason", [
    ({"relevance": 0.8}, None),
    ({"relevance": 0.79}, "below_threshold"),
    ({"freshness": "2026-06-24T12:00:00Z"}, None),
    ({"freshness": "2026-06-24T11:59:59Z"}, "not_eligible"),
    ({"relevance": 0.5, "freshness": "2026-01-01T00:00:00Z"}, "below_threshold"),
])
def test_threshold_and_age_eligibility(with_eligibility, fields, reason):
    add(with_eligibility, "policy-corpus", knowledge(**fields))
    assert exclusions(with_eligibility) == ([("kb:x", reason)] if reason else [])


def test_an_item_without_a_score_cannot_clear_a_threshold(fixture_snapshot):
    fixture_snapshot["route_policy"]["producers"]["crm-mcp"] = {"kind": "mcp", "slots": ["evidence.tool_results"]}
    fixture_snapshot["route_policy"]["slots"] = {"evidence.tool_results": {"min_relevance": 0.5}}
    add_batch(fixture_snapshot, "crm-mcp", "mcp", observation("obs:1"))
    assert exclusions(fixture_snapshot) == [("obs:1", "below_threshold")]


# R-3: omitted policy fields come from the slot defaults, replaced by the route's versioned overrides.

def test_route_overrides_replace_slot_defaults_and_are_traced(fixture_snapshot):
    from cwa.admission import admit

    fixture_snapshot["route_policy"]["default_overrides"] = {"evidence.knowledge": {"token_budget": 420, "lineage": "extracted"}}
    add(fixture_snapshot, "policy-corpus", knowledge(id="kb:filled"), knowledge(id="kb:explicit", token_budget=90, lineage="verbatim", variants=[],
                                                                                  conflict_policy="defers", eligibility="route-policy", injection_risk="untrusted_content"))
    admission = admit(Snapshot.from_json(fixture_snapshot))
    by_id = {item.id: item for item in admission.items}
    assert (by_id["kb:filled"].token_budget, by_id["kb:filled"].lineage, by_id["kb:filled"].conflict_policy) == (420, "extracted", "defers")
    assert (by_id["kb:explicit"].token_budget, by_id["kb:explicit"].lineage) == (90, "verbatim")
    assert [f for i, f in admission.defaults_filled if i == "kb:filled"] == list(("token_budget", "variants", "conflict_policy", "lineage", "eligibility", "injection_risk"))
    assert [f for i, f in admission.defaults_filled if i == "kb:explicit"] == []


@pytest.mark.parametrize("authority, reason", [("generated", None), ("untrusted", None), ("state", "authority_not_allowed"), ("user", "authority_not_allowed")])
def test_memory_is_generated_or_untrusted_never_state(fixture_snapshot, authority, reason):
    place(fixture_snapshot, "interaction.memory")
    add(fixture_snapshot, "memory-svc", memory(authority=authority))
    assert exclusions(fixture_snapshot) == ([("m:1", reason)] if reason else [])
