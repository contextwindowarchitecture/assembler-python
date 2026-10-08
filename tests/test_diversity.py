"""Route-requested source diversity (R-26): conformance/README.md's Source diversity section.

In the slots a route caps, each pair of authenticated producer and source keeps at most max_per_source
items after deduplication, whether or not the payload fits. Protected items and items a conflict group
names are never excluded and take places first; the others fill what is left in the slot's rank.
"""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def case(name: str) -> dict:
    return read_json(CASES / name / "snapshot.json")


def candidate(snapshot: dict, item_id: str) -> dict:
    return next(i for b in snapshot["batches"] for i in b["items"] if i.get("id") == item_id)


def capped(snapshot: dict) -> list[str]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return [row["item_id"] for row in trace["excluded"] if row["reason"] == "source_diversity_cap"]


# diversity-cap: doc:refunds from policy-corpus holds kb:a1-copy (0.95, kb:a1's duplicate), kb:a2 (0.85),
# kb:a3 (0.8) and kb:a4 (0.7); wiki-corpus sends wiki:a1 and wiki:a2 from the same source string.

def test_each_source_keeps_its_highest_ranked_items_up_to_the_cap():
    assert capped(case("diversity-cap")) == ["kb:a3", "kb:a4"]


def test_capped_rows_carry_the_slot_and_nothing_else():
    trace = assemble(Snapshot.from_json(case("diversity-cap"))).trace
    assert {"item_id": "kb:a3", "reason": "source_diversity_cap", "stage": "assembler", "slot": "evidence.knowledge"} in trace["excluded"]


def test_the_cap_holds_although_the_payload_fits():
    snapshot = case("diversity-cap")
    snapshot["budget"]["input"] = 1_000_000
    assert capped(snapshot) == ["kb:a3", "kb:a4"]


def test_a_duplicate_takes_no_place():
    snapshot = case("diversity-cap")
    del snapshot["route_policy"]["slots"]["evidence.knowledge"]["dedupe"]
    assert capped(snapshot) == ["kb:a2", "kb:a3", "kb:a4"]  # kb:a1-copy and kb:a1 take both places


def test_another_producers_items_with_the_same_source_count_apart():
    snapshot = case("diversity-cap")
    snapshot["route_policy"]["slots"]["evidence.knowledge"]["max_per_source"] = 1
    assert "wiki:a1" not in capped(snapshot) and "wiki:a2" in capped(snapshot)


@pytest.mark.parametrize("cap, expected", [(3, ["kb:a4"]), (4, [])])
def test_a_source_at_or_under_the_cap_is_untouched(cap, expected):
    snapshot = case("diversity-cap")
    snapshot["route_policy"]["slots"]["evidence.knowledge"]["max_per_source"] = cap
    assert capped(snapshot) == expected


@pytest.mark.parametrize("cap, expected", [(2.0, ["kb:a3", "kb:a4"]), (2**53 + 1, [])])
def test_a_cap_read_as_a_double_caps_like_its_integer(cap, expected):
    """conformance/README.md, Numbers: 2.0 is 2, and 2^53 + 1 is the double 2^53, which the boundary makes a float."""
    snapshot = case("diversity-cap")
    snapshot["route_policy"]["slots"]["evidence.knowledge"]["max_per_source"] = cap
    assert capped(snapshot) == expected


@pytest.mark.parametrize("rules", [None, {"supersede": "source", "dedupe": "exact"}])
def test_a_slot_without_max_per_source_is_not_capped(rules):
    snapshot = case("diversity-cap")
    slots = snapshot["route_policy"]["slots"]
    slots.pop("evidence.knowledge")
    slots["evidence.knowledge"] = {"min_relevance": 0.5, "required_scope": ["tenant"], **(rules or {})}
    assert capped(snapshot) == []


# diversity-exemptions: kb:w1 (0.55) wins the fact group; kb:w2 (0.9) and kb:w3 (0.8) share doc:policy;
# state.user is raised to protected and capped at one.

def test_exempt_items_take_places_first():
    assert capped(case("diversity-exemptions")) == ["kb:w3"]


def test_a_source_with_as_many_exempt_items_as_the_cap_keeps_no_other():
    snapshot = case("diversity-exemptions")
    rules = snapshot["route_policy"]["slots"]["evidence.knowledge"]
    rules["max_per_source"] = 1
    del rules["dedupe"]  # so kb:w2 and kb:w2-copy both reach the cap
    snapshot["conflicts"].append({"id": "g-extra", "kind": "instruction", "items": ["kb:w3", "turn:18"]})  # exempts kb:w3
    assert capped(snapshot) == ["kb:w2", "kb:w2-copy"]


def test_exempt_items_over_the_cap_all_stay():
    trace = assemble(Snapshot.from_json(case("diversity-exemptions"))).trace
    assert {"user:plan", "user:region"} <= {row["item_id"] for row in trace["included"]}


def test_without_the_upgrade_a_state_source_is_capped():
    snapshot = case("diversity-exemptions")
    del snapshot["route_policy"]["tier_upgrades"]
    assert "user:region" in capped(snapshot)  # user:plan and user:region tie; id decides


def test_rows_follow_the_pipeline():
    trace = assemble(Snapshot.from_json(case("diversity-exemptions"))).trace
    assert [row["reason"] for row in trace["excluded"]] == ["conflict_lost", "superseded", "duplicate_content", "source_diversity_cap"]


def test_a_route_that_needs_evidence_refuses_when_the_cap_leaves_too_little():
    trace = assemble(Snapshot.from_json(case("diversity-evidence-required"))).trace
    assert trace["refused"]["reason"] == "evidence_required"
    assert trace["recovery"] == {"action": "request_context"}
    assert [row["reason"] for row in trace["excluded"]] == ["source_diversity_cap"]
