"""Fitting: shedding under budget pressure, in tier order and by the route's fitting policy (R-16).

The procedure is conformance/README.md's Fitting section. Token counts below are fixture-whitespace
counts of the fixture-xml payload.
"""
from __future__ import annotations

import pytest

from cwa import Snapshot, assemble
from conftest import CASES, read_json


def case(name: str) -> dict:
    return read_json(CASES / name / "snapshot.json")


def candidate(snapshot: dict, item_id: str) -> dict:
    return next(i for b in snapshot["batches"] for i in b["items"] if i.get("id") == item_id)


def omitted(snapshot: dict) -> list[str]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return [row["item_id"] for row in trace["excluded"] if row["reason"] == "over_budget"]


def included(snapshot: dict) -> list[str]:
    return [row["item_id"] for row in assemble(Snapshot.from_json(snapshot)).trace["included"]]


# budget-droppable-order renders 58 tokens against a budget of 44: user:plan is 3 words, ex:1 7, ex:2 6,
# and each occurrence adds 3 wrapper tokens.

def test_droppable_items_shed_by_slot_priority_then_lowest_rank_and_stop_once_the_payload_fits():
    snapshot = case("budget-droppable-order")
    assert omitted(snapshot) == ["user:plan", "ex:1"]
    assert included(snapshot) == ["policy:v12", "ex:2", "kb:a", "turn:18"]


def test_equal_priorities_shed_in_slot_name_order():
    snapshot = case("budget-droppable-order")
    del snapshot["route_policy"]["slots"]["governance.examples"]
    assert omitted(snapshot) == ["ex:1", "ex:2"]


def test_order_by_freshness_keeps_older_items_longer():
    snapshot = case("budget-droppable-order")
    snapshot["route_policy"]["slots"]["governance.examples"]["order_by"] = ["freshness"]
    assert omitted(snapshot) == ["user:plan", "ex:2"]


def test_unscored_items_rank_below_scored_ones():
    snapshot = case("budget-droppable-order")
    candidate(snapshot, "ex:1")["relevance"] = 0.1
    assert omitted(snapshot) == ["user:plan", "ex:2"]


def test_an_item_that_volunteers_droppable_sheds_with_the_droppable_items():
    snapshot = case("budget-droppable-order")
    del snapshot["route_policy"]["slots"]["governance.examples"]
    candidate(snapshot, "kb:a")["tier"] = "droppable"
    assert omitted(snapshot) == ["kb:a", "ex:1"]


def test_over_budget_rows_name_the_slot_after_the_admission_rows():
    snapshot = case("budget-droppable-order")
    candidate(snapshot, "kb:a")["relevance"] = 0.1  # below the route's 0.5 threshold
    trace = assemble(Snapshot.from_json(snapshot)).trace
    assert trace["excluded"] == [
        {"item_id": "kb:a", "reason": "below_threshold", "stage": "assembler", "slot": "evidence.knowledge"},
        {"item_id": "user:plan", "reason": "over_budget", "stage": "assembler", "slot": "state.user"},
    ]


def compressed(snapshot: dict) -> list[tuple[str, str]]:
    trace = assemble(Snapshot.from_json(snapshot)).trace
    return [(row["item_id"], row["variant_id"]) for row in trace["compressed"]]


# budget-variant-choice: after ex:1 goes, neither of kb:b's variants fits, so it takes the shortest; kb:a~mid
# fits, so kb:a takes it over the shorter kb:a~short. History is never reached.

def test_compressible_items_take_the_longest_variant_that_fits_else_the_shortest():
    trace = assemble(Snapshot.from_json(case("budget-variant-choice"))).trace
    assert trace["compressed"] == [
        {"slot": "evidence.knowledge", "item_id": "kb:a", "from": 23, "to": 10, "method": "extract", "variant_id": "kb:a~mid"},
        {"slot": "evidence.knowledge", "item_id": "kb:b", "from": 15, "to": 3, "method": "extract", "variant_id": "kb:b~short"},
    ]
    assert [(row["item_id"], row["tokens"]) for row in trace["included"] if row["slot"] == "evidence.knowledge"] == [("kb:a", 10), ("kb:b", 3)]
    assert [row["item_id"] for row in trace["excluded"]] == ["ex:1"]


def test_variants_with_equal_counts_prefer_the_earlier_one():
    snapshot = case("budget-variant-choice")
    candidate(snapshot, "kb:b")["variants"].insert(0, {"id": "kb:b~alt", "body": "Annual: prorated refunds.", "method": "extract",
                                                      "lineage": "extracted"})
    assert ("kb:b", "kb:b~alt") in compressed(snapshot)


# budget-omit-after-variants: history (priority 0) sheds before knowledge (priority 1), oldest turn first.

def test_every_compress_step_runs_before_any_omission():
    snapshot = case("budget-omit-after-variants")
    assert compressed(snapshot) == [("kb:a", "kb:a~short")]
    assert omitted(snapshot) == ["turn:14", "turn:15"]


def test_protected_items_are_never_compressed_or_omitted():
    snapshot = case("budget-omit-after-variants")
    candidate(snapshot, "policy:v12")["variants"] = [{"id": "policy:v12~short", "body": "Cite evidence.", "method": "extract",
                                                      "lineage": "extracted"}]
    assert compressed(snapshot) == [("kb:a", "kb:a~short")]
    assert "policy:v12" in included(snapshot)


def test_a_slot_placed_twice_is_compressed_in_both_occurrences():
    snapshot = case("budget-variant-choice")
    snapshot["profile"]["placement"].insert(-1, {"slot": "evidence.knowledge", "wrap": "xml:evidence.knowledge"})
    snapshot["budget"]["input"] = 90
    trace = assemble(Snapshot.from_json(snapshot)).trace
    rows = [(row["item_id"], row["variant_id"], row["to"]) for row in trace["compressed"]]
    assert rows == [("kb:a", "kb:a~mid", 10), ("kb:b", "kb:b~short", 3)] * 2
    assert [row["tokens"] for row in trace["included"] if row["slot"] == "evidence.knowledge"] == [10, 3, 10, 3]


# budget-route-order: the route omits knowledge before any variant is selected, oldest first.

def test_the_routes_fitting_order_runs_before_the_default_steps():
    snapshot = case("budget-route-order")
    assert omitted(snapshot) == ["kb:old"]
    assert compressed(snapshot) == []


def test_without_a_route_order_the_same_items_are_compressed_instead():
    snapshot = case("budget-route-order")
    del snapshot["route_policy"]["fitting_order"]
    assert omitted(snapshot) == []
    assert compressed(snapshot) == [("kb:old", "kb:old~short")]


# budget-route-tiers: the route raises state.user to protected and governance.examples to compressible.

def test_fitting_uses_the_tiers_the_route_raised():
    snapshot = case("budget-route-tiers")
    assert omitted(snapshot) == ["kb:faq"]
    assert compressed(snapshot) == [("ex:1", "ex:1~short"), ("ex:2", "ex:2~short")]
    assert "user:plan" in included(snapshot)


def test_without_the_upgrades_the_same_items_shed_at_their_default_tiers():
    snapshot = case("budget-route-tiers")
    del snapshot["route_policy"]["tier_upgrades"]
    assert omitted(snapshot) == ["kb:faq", "ex:1"]
    assert compressed(snapshot) == []


# budget-token-caps: kb:b (11 tokens, cap 6) has no variant within its cap; kb:a (16, cap 12) takes kb:a~mid (10);
# ex:1 (7, cap 4) is droppable. After the caps the payload is 55 tokens against a budget of 52.

def test_items_over_their_cap_are_reduced_in_shedding_order_before_budget_pressure():
    snapshot = case("budget-token-caps")
    assert omitted(snapshot) == ["kb:b", "ex:1"]
    trace = assemble(Snapshot.from_json(snapshot)).trace
    assert trace["compressed"] == [
        {"slot": "evidence.knowledge", "item_id": "kb:a", "from": 16, "to": 5, "method": "extract", "variant_id": "kb:a~short"}]


def test_caps_apply_even_when_the_payload_fits():
    snapshot = case("budget-token-caps")
    snapshot["budget"]["input"] = 4096
    assert omitted(snapshot) == ["kb:b", "ex:1"]
    assert compressed(snapshot) == [("kb:a", "kb:a~mid")]


def test_an_item_exactly_at_its_cap_is_untouched():
    snapshot = case("budget-token-caps")
    snapshot["budget"]["input"] = 4096
    candidate(snapshot, "kb:b")["token_budget"] = 11
    assert omitted(snapshot) == ["ex:1"]
    assert "kb:b" in included(snapshot)
