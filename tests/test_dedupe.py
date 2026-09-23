"""Route-requested exact deduplication (R-24): conformance/README.md's Deduplication section.

In the slots a route asks, an item whose key (body with whitespace runs collapsed, ends trimmed)
equals a kept item's key is excluded as duplicate_content, after conflict resolution and before any
refusal check. Protected items and items a conflict group names are never excluded.
"""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def case(name: str) -> dict:
    return read_json(CASES / name / "snapshot.json")


def candidate(snapshot: dict, item_id: str) -> dict:
    return next(i for b in snapshot["batches"] for i in b["items"] if i.get("id") == item_id)


def duplicates(snapshot: dict) -> dict[str, str]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return {row["item_id"]: row["duplicate_of"] for row in trace["excluded"] if row["reason"] == "duplicate_content"}


# dedupe-exact: kb:mirror (0.95), kb:a (0.9) and kb:spaced (0.6, whitespace only) share a key;
# kb:tie-1 and kb:tie-2 tie on relevance and freshness; obs:new is newer than obs:old.

def test_equal_keys_in_a_deduplicated_slot_keep_the_highest_ranked_copy():
    assert duplicates(case("dedupe-exact")) == {"kb:a": "kb:mirror", "kb:spaced": "kb:mirror", "kb:tie-2": "kb:tie-1", "obs:old": "obs:new"}


def test_duplicate_rows_carry_the_slot_and_the_kept_item():
    trace = assemble(Snapshot.from_json(case("dedupe-exact"))).trace
    assert trace["excluded"][0] == {"item_id": "kb:a", "reason": "duplicate_content", "stage": "assembler",
                                    "slot": "evidence.knowledge", "duplicate_of": "kb:mirror"}


@pytest.mark.parametrize("rules", [None, {"priority": 1, "max_tokens": 4096}])
def test_a_slot_without_dedupe_keeps_equal_bodies(rules):
    snapshot = case("dedupe-exact")
    slots = snapshot["route_policy"]["slots"]
    del slots["evidence.tool_results"]
    if rules:
        slots["evidence.tool_results"] = rules
    assert "obs:old" not in duplicates(snapshot)


@pytest.mark.parametrize("separator, duplicate", [
    ("\u2028", True), ("\u205f", True), ("\u200b", False), ("\u001c", False), ("", False)])
def test_only_ecmascript_whitespace_collapses(separator, duplicate):
    """U+200B (zero width space) and U+001C are not ECMAScript whitespace; Python's \\s matches U+001C."""
    snapshot = case("dedupe-exact")
    candidate(snapshot, "kb:spaced")["body"] = f"Pro plans refund in full{separator}within 30 days."
    assert ("kb:spaced" in duplicates(snapshot)) is duplicate


def test_items_in_different_slots_are_never_compared():
    snapshot = case("dedupe-exact")
    candidate(snapshot, "obs:new")["freshness"] = "2026-09-22T11:40:00Z"  # obs:old now ranks first
    assert duplicates(snapshot)["obs:new"] == "obs:old"
    assert "kb:mirror" not in duplicates(snapshot)


def test_bodies_are_compared_whatever_their_variants():
    snapshot = case("dedupe-exact")
    candidate(snapshot, "kb:a")["variants"] = [{"id": "kb:a~short", "body": "Pro: 30 days.", "method": "extract", "lineage": "extracted"}]
    assert duplicates(snapshot)["kb:a"] == "kb:mirror"


# dedupe-exemptions: the fact group f-window keeps kb:window and excludes wiki:window; g-fee is moot.

def test_a_conflict_group_member_stays_and_its_ungrouped_copy_goes():
    assert duplicates(case("dedupe-exemptions")) == {"kb:fee-copy": "kb:fee", "kb:window-copy": "kb:window"}


def test_protected_copies_are_all_kept():
    trace = assemble(Snapshot.from_json(case("dedupe-exemptions"))).trace
    assert {"user:plan", "user:plan-sync"} <= {row["item_id"] for row in trace["included"]}


def test_without_the_upgrade_protected_copies_would_deduplicate():
    snapshot = case("dedupe-exemptions")
    del snapshot["route_policy"]["tier_upgrades"]
    assert duplicates(snapshot)["user:plan-sync"] == "user:plan"


def test_a_conflict_loser_is_gone_before_deduplication():
    snapshot = case("dedupe-exemptions")
    candidate(snapshot, "kb:window-copy")["body"] = candidate(snapshot, "wiki:window")["body"]
    assert "kb:window-copy" not in duplicates(snapshot)


def test_deduplication_rows_follow_conflict_rows_and_precede_fitting_rows():
    snapshot = case("dedupe-exemptions")
    snapshot["budget"]["input"] = 50  # 53 tokens: fitting must omit something
    reasons = [row["reason"] for row in assemble(Snapshot.from_json(snapshot)).trace["excluded"]]
    assert reasons == ["below_threshold", "conflict_lost", "duplicate_content", "duplicate_content", "over_budget"]


def test_a_conflict_refusal_keeps_the_deduplication_rows():
    snapshot = case("dedupe-exemptions")
    snapshot["route_policy"]["facts"]["refund.window"]["precedence"] = ["nobody"]  # no member eligible: refuse
    trace = assemble(Snapshot.from_json(snapshot)).trace
    assert trace["refused"]["reason"] == "conflict_unresolved"
    assert [row["item_id"] for row in trace["excluded"] if row["reason"] == "duplicate_content"] == ["kb:fee-copy", "kb:window-copy"]


def test_a_route_that_needs_evidence_refuses_when_deduplication_leaves_too_little():
    trace = assemble(Snapshot.from_json(case("dedupe-evidence-required"))).trace
    assert trace["refused"]["reason"] == "evidence_required"
    assert trace["recovery"] == {"action": "request_context"}
