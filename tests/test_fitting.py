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
