"""Route-requested supersession of stale observations (R-25): conformance/README.md's Supersession section.

In the slots a route asks, an item is superseded when the same authenticated producer sent an item with
the same source and a later freshness, compared as instants at full precision. Items tied for the latest
freshness all stay. It runs after conflict resolution and before deduplication, and never excludes a
protected item or an item a conflict group names.
"""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def case(name: str) -> dict:
    return read_json(CASES / name / "snapshot.json")


def candidate(snapshot: dict, item_id: str) -> dict:
    return next(i for b in snapshot["batches"] for i in b["items"] if i.get("id") == item_id)


def superseded(snapshot: dict) -> dict[str, str]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return {row["item_id"]: row["superseded_by"] for row in trace["excluded"] if row["reason"] == "superseded"}


# supersede-observations: obs:order-1..3c share crm-mcp and crm:order/42; obs:order-3, -3b and -3c are
# the same instant written three ways; obs:refund-b is one microsecond after obs:refund-a.

def test_only_the_latest_observation_of_a_call_stays():
    assert superseded(case("supersede-observations")) == {
        "obs:order-1": "obs:order-3", "obs:order-2": "obs:order-3", "obs:refund-a": "obs:refund-b"}


def test_superseded_rows_carry_the_slot_and_the_latest_item():
    trace = assemble(Snapshot.from_json(case("supersede-observations"))).trace
    assert trace["excluded"][0] == {"item_id": "obs:order-1", "reason": "superseded", "stage": "assembler",
                                    "slot": "evidence.tool_results", "superseded_by": "obs:order-3"}


def test_items_tied_for_the_latest_instant_all_stay():
    included = {row["item_id"] for row in assemble(Snapshot.from_json(case("supersede-observations"))).trace["included"]}
    assert {"obs:order-3", "obs:order-3b", "obs:order-3c"} <= included


def test_superseded_by_names_the_highest_ranked_latest_item_however_its_instant_is_written():
    snapshot = case("supersede-observations")
    candidate(snapshot, "obs:order-3c")["relevance"] = 0.9  # scored, so it ranks above its unscored ties
    assert superseded(snapshot)["obs:order-1"] == "obs:order-3c"


@pytest.mark.parametrize("older, newer, stale", [
    ("2026-09-22T11:59:00Z", "2026-09-22T11:59:00.0000001Z", True),  # later only in the seventh fractional digit
    ("2026-09-22T11:59:00Z", "2026-09-22T11:59:00.000000Z", False),  # the same instant: a tie
    ("2026-09-22T11:59:00.000001Z", "2026-09-22T12:59:00.000001+01:00", False)])  # the same instant, another offset
def test_instants_compare_at_full_precision(older, newer, stale):
    snapshot = case("supersede-observations")
    candidate(snapshot, "obs:refund-a")["freshness"] = older
    candidate(snapshot, "obs:refund-b")["freshness"] = newer
    assert ("obs:refund-a" in superseded(snapshot)) is stale


def test_the_same_source_from_another_producer_is_another_call():
    snapshot = case("supersede-observations")
    candidate(snapshot, "obs:billing-42")["freshness"] = "2026-09-22T11:59:30Z"  # later than every crm-mcp poll
    assert superseded(snapshot)["obs:order-1"] == "obs:order-3"
    assert "obs:order-3" not in superseded(snapshot)


@pytest.mark.parametrize("rules", [None, {"dedupe": "exact"}])
def test_a_slot_without_supersede_keeps_every_observation(rules):
    snapshot = case("supersede-observations")
    slots = snapshot["route_policy"]["slots"]
    del slots["evidence.tool_results"]
    if rules:
        slots["evidence.tool_results"] = rules
    assert superseded(snapshot) == {}


def test_bodies_and_source_versions_do_not_decide():
    snapshot = case("supersede-observations")
    candidate(snapshot, "obs:order-1")["source_version"] = "99"
    candidate(snapshot, "obs:order-1")["body"] = "order 42: shipped"
    assert superseded(snapshot)["obs:order-1"] == "obs:order-3"


# supersede-exemptions: obs:status-old wins the fact group f-status; state.user is raised to protected;
# obs:ship-old and obs:ship-new share a source and a body, and obs:ship-mirror differs only in spacing.

def test_a_conflict_group_member_and_a_protected_item_stay_although_stale():
    trace = assemble(Snapshot.from_json(case("supersede-exemptions"))).trace
    assert {"obs:status-old", "user:plan-old"} <= {row["item_id"] for row in trace["included"]}


def test_without_the_upgrade_a_stale_state_item_is_superseded():
    snapshot = case("supersede-exemptions")
    del snapshot["route_policy"]["tier_upgrades"]
    assert superseded(snapshot)["user:plan-old"] == "user:plan-new"


def test_supersession_runs_before_deduplication():
    trace = assemble(Snapshot.from_json(case("supersede-exemptions"))).trace
    assert [(row["item_id"], row["reason"]) for row in trace["excluded"]] == [
        ("kb:status", "conflict_lost"), ("obs:ship-old", "superseded"), ("obs:ship-mirror", "duplicate_content")]


def test_a_conflict_loser_never_supersedes():
    snapshot = case("supersede-exemptions")
    snapshot["route_policy"]["facts"]["order.status"]["precedence"] = ["policy-corpus"]  # kb:status wins now
    candidate(snapshot, "obs:status-old")["freshness"] = "2026-09-22T11:59:00Z"  # the loser is now the latest
    trace = assemble(Snapshot.from_json(snapshot)).trace
    assert ("obs:status-old", "conflict_lost") in [(r["item_id"], r["reason"]) for r in trace["excluded"]]
    assert "obs:status-new" in {row["item_id"] for row in trace["included"]}


def test_a_route_that_needs_evidence_refuses_when_supersession_leaves_too_little():
    trace = assemble(Snapshot.from_json(case("supersede-evidence-required"))).trace
    assert trace["refused"]["reason"] == "evidence_required"
    assert trace["recovery"] == {"action": "request_context"}
    assert [row["reason"] for row in trace["excluded"]] == ["superseded"]
