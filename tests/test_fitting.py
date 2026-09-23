"""Fitting: shedding under budget pressure, in tier order and by the route's fitting policy (R-16).

The procedure is conformance/README.md's Fitting section. Token counts below are fixture-whitespace
counts of the fixture-xml payload.
"""
from __future__ import annotations

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


# budget-slot-caps (R-16, route max_tokens): after kb:gift (5 tokens, cap 3, no variants) goes for its own
# cap and kb:a takes kb:a~mid (10), knowledge holds kb:a 10 + kb:b 15 + kb:faq 12 = 37 against 12, and
# history holds turn:15 12 + turn:16 7 = 19 against 13. The payload fits a budget of 4096 throughout.

def test_slots_over_their_max_tokens_shed_their_own_items_although_the_payload_fits():
    snapshot = case("budget-slot-caps")
    assert omitted(snapshot) == ["kb:gift", "turn:15", "kb:faq"]
    assert compressed(snapshot) == [("kb:a", "kb:a~short"), ("kb:b", "kb:b~short")]
    assert included(snapshot) == ["policy:v12", "ex:1", "user:plan", "kb:a", "kb:b", "turn:16", "turn:18"]


def test_a_slot_exactly_at_its_max_tokens_is_untouched():
    snapshot = case("budget-slot-caps")
    snapshot["route_policy"]["slots"]["interaction.history"]["max_tokens"] = 19
    assert "turn:15" not in omitted(snapshot)


def test_a_slot_without_max_tokens_has_no_cap():
    snapshot = case("budget-slot-caps")
    del snapshot["route_policy"]["slots"]["evidence.knowledge"]["max_tokens"]
    assert omitted(snapshot) == ["kb:gift", "turn:15"]
    assert compressed(snapshot) == [("kb:a", "kb:a~mid")]


def test_without_a_route_step_a_capped_slot_takes_variants_before_omitting():
    snapshot = case("budget-slot-caps")
    del snapshot["route_policy"]["fitting_order"]
    assert "turn:15" not in omitted(snapshot)
    assert ("turn:15", "turn:15~sum") in compressed(snapshot)


def test_capped_slots_shed_in_slot_shedding_order():
    snapshot = case("budget-slot-caps")
    del snapshot["route_policy"]["slots"]["interaction.history"]["priority"]
    assert omitted(snapshot) == ["kb:gift", "kb:faq", "turn:15"]


# budget-slot-cap-before-pressure: 69 tokens against 60. Capping knowledge at 20 takes kb:b~short and
# leaves 57, so budget pressure, which would have omitted ex:1 first, never runs.

def test_slot_caps_run_before_budget_pressure():
    snapshot = case("budget-slot-cap-before-pressure")
    assert omitted(snapshot) == []
    assert compressed(snapshot) == [("kb:b", "kb:b~short")]
    assert "ex:1" in included(snapshot)


# budget-slot-floor (R-16, route min_tokens): 77 tokens against 65. governance.examples holds ex:1 (7) at a
# floor of 5; history (turn:15 12, turn:16 3, priority -1, oldest first) has a floor of 10.

def test_a_floor_withholds_a_reduction_and_freezes_its_slot():
    snapshot = case("budget-slot-floor")
    assert omitted(snapshot) == ["kb:b"]
    assert compressed(snapshot) == [("kb:a", "kb:a~short")]
    assert {"ex:1", "turn:15", "turn:16"} <= set(included(snapshot))


def test_a_frozen_slot_keeps_a_reduction_that_alone_would_have_kept_its_floor():
    """Skipping turn:15 and omitting turn:16 (15 → 12, above 10) would be the skip-and-continue reading."""
    snapshot = case("budget-slot-floor")
    snapshot["budget"]["input"] = 59  # kb:b alone no longer suffices
    assert "turn:16" not in omitted(snapshot)


def test_a_compression_that_would_break_a_floor_is_withheld_and_freezes_the_slot():
    snapshot = case("budget-slot-floor")
    candidate(snapshot, "turn:15")["variants"] = [{"id": "turn:15~sum", "body": "Seats wrong.", "method": "summary", "lineage": "extracted"}]
    # history's compress step runs first (priority -1): 15 → 5 tokens would break its floor of 10.
    assert ("turn:15", "turn:15~sum") not in compressed(snapshot)
    assert omitted(snapshot) == ["kb:b"]


def test_a_floored_slot_may_keep_droppable_items_while_others_compress():
    trace = assemble(Snapshot.from_json(case("budget-slot-floor"))).trace
    assert "ex:1" in {row["item_id"] for row in trace["included"]} and trace["compressed"]


def test_without_floors_the_same_route_sheds_the_example_first():
    snapshot = case("budget-slot-floor")
    for rules in snapshot["route_policy"]["slots"].values():
        rules.pop("min_tokens", None)
    assert omitted(snapshot)[0] == "ex:1"


def test_a_reduction_that_keeps_the_slot_at_its_floor_is_made():
    snapshot = case("budget-slot-floor")
    del snapshot["route_policy"]["slots"]["governance.examples"]
    snapshot["route_policy"]["slots"]["interaction.history"]["min_tokens"] = 3  # 15 - 12 = 3: exactly the floor
    snapshot["budget"]["input"] = 50
    assert omitted(snapshot) == ["ex:1", "turn:15"]


def test_a_floor_counts_every_occurrence_of_a_slot_placed_twice():
    snapshot = case("budget-slot-floor")
    snapshot["profile"]["placement"].append({"slot": "interaction.history", "wrap": "xml:interaction.history"})
    snapshot["route_policy"]["slots"]["interaction.history"]["min_tokens"] = 5
    snapshot["budget"]["input"] = 70
    # 98 tokens; after kb:a~short, omitting turn:15 leaves history 2 x 3 = 6, not below 5, and the payload 63.
    assert omitted(snapshot) == ["turn:15"]


def test_floors_do_not_guard_slot_caps():
    snapshot = case("budget-slot-floor-under-cap")
    assert omitted(snapshot) == ["turn:15", "ex:1", "kb:b"]
    assert "turn:16" in included(snapshot)


# budget-margin (R-16, budget.margin_percent): the payload renders 58 tokens, within budget.input 60, but a 10%
# margin charges ceil(58 x 1.1) = 64. Omitting user:plan leaves 52, charged 58; omitting ex:1 too leaves 42, charged 47.

def test_a_margin_sheds_until_the_charged_count_fits():
    snapshot = case("budget-margin")
    assert omitted(snapshot) == ["user:plan"]
    del snapshot["budget"]["margin_percent"]
    assert omitted(snapshot) == []


def test_the_charged_count_rounds_up():
    snapshot = case("budget-margin")
    snapshot["budget"]["input"] = 58  # 52 x 1.1 = 57.2, charged 58: fits
    assert omitted(snapshot) == ["user:plan"]
    snapshot["budget"]["input"] = 57  # charged 58 does not fit, though 57.2 rounds down to 57
    assert omitted(snapshot) == ["user:plan", "ex:1"]


def test_traced_counts_stay_unscaled_and_the_budget_repeats_the_margin():
    trace = assemble(Snapshot.from_json(case("budget-margin"))).trace
    assert trace["result"]["input_tokens"] == 52
    assert trace["budget"] == {"input": 60, "reserved_output": 1024, "margin_percent": 10}
    assert "margin_percent" not in assemble(Snapshot.from_json(case("budget-droppable-order"))).trace["budget"]
    snapshot = case("budget-droppable-order")
    snapshot["budget"]["margin_percent"] = 0
    assert assemble(Snapshot.from_json(snapshot)).trace["budget"]["margin_percent"] == 0


def test_caps_compare_unscaled_counts():
    snapshot = case("budget-margin")
    snapshot["budget"]["input"] = 4096
    candidate(snapshot, "kb:a")["token_budget"] = 8  # kb:a renders 8 tokens: at its cap, however large the margin
    snapshot["route_policy"]["slots"]["governance.examples"]["max_tokens"] = 13  # ex:1 7 + ex:2 6: at the slot cap
    snapshot["budget"]["margin_percent"] = 100
    assert omitted(snapshot) == []
