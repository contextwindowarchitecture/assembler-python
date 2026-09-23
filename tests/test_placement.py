"""Placement (R-20): a profile must not omit admitted protected content.

An unprotected item whose slot the profile does not place is excluded with slot_unplaced, the last
admission check. A protected one is admitted, and assembly refuses with protected_slot_unplaced,
right after required_slot_missing (R-21).
"""
from __future__ import annotations

import copy

from cwa import Snapshot, assemble


def turn(id: str = "turn:17", **fields) -> dict:
    item = {"id": id, "slot": "interaction.history", "source": "conversation", "source_version": "1",
            "authority": "user", "trust": "unverified", "freshness": "2026-09-22T11:58:00Z", "body": "I bought the Pro plan."}
    return {**item, **fields}


def memory(id: str = "mem:1", **fields) -> dict:
    item = {"id": id, "slot": "interaction.memory", "source": "turn:3", "source_version": "1", "authority": "generated",
            "trust": "unverified", "freshness": "2026-09-20T00:00:00Z", "expires": "2026-12-01T00:00:00Z", "body": "Prefers email."}
    return {**item, **fields}


def add(snapshot: dict, producer: str, *items: dict) -> dict:
    next(b for b in snapshot["batches"] if b["producer"]["id"] == producer)["items"].extend(copy.deepcopy(items))
    return snapshot


def assembler_rows(result) -> list[tuple[str, str, str | None]]:
    return [(r["item_id"], r["reason"], r.get("slot")) for r in result.trace["excluded"] if r["stage"] == "assembler"]


def test_items_in_slots_the_profile_does_not_place_are_excluded_with_their_slot(fixture_snapshot):
    placed = assemble(Snapshot.from_json(fixture_snapshot))
    add(fixture_snapshot, "conversation", turn())
    add(fixture_snapshot, "memory-svc", memory())
    result = assemble(Snapshot.from_json(fixture_snapshot))
    # Admission rows are ordered by producer id: conversation, then memory-svc.
    assert assembler_rows(result) == [("turn:17", "slot_unplaced", "interaction.history"), ("mem:1", "slot_unplaced", "interaction.memory")]
    assert result.payload == placed.payload


def test_every_earlier_admission_check_comes_before_placement(fixture_snapshot):
    add(fixture_snapshot, "memory-svc", memory(expires="2026-09-01T00:00:00Z"))
    assert assembler_rows(assemble(Snapshot.from_json(fixture_snapshot))) == [("mem:1", "expired", "interaction.memory")]


def test_a_protected_item_in_an_unplaced_slot_refuses_rather_than_being_dropped(fixture_snapshot):
    fixture_snapshot["route_policy"]["tier_upgrades"] = {"interaction.history": "protected"}
    add(fixture_snapshot, "conversation", turn())
    add(fixture_snapshot, "memory-svc", memory())
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert result.payload is None and result.trace["result"] is None and result.trace["included"] == []
    assert result.trace["refused"] == {"bool": True, "reason": "protected_slot_unplaced"}
    assert assembler_rows(result) == [("mem:1", "slot_unplaced", "interaction.memory")]


def test_a_missing_required_slot_is_reported_before_an_unplaced_protected_item(fixture_snapshot):
    fixture_snapshot["route_policy"]["tier_upgrades"] = {"interaction.history": "protected"}
    add(fixture_snapshot, "conversation", turn())
    next(b for b in fixture_snapshot["batches"] if b["producer"]["id"] == "policy-registry")["items"].clear()
    assert assemble(Snapshot.from_json(fixture_snapshot)).trace["refused"]["reason"] == "required_slot_missing"


def test_an_unplaced_protected_item_is_reported_before_an_unresolved_conflict(fixture_snapshot):
    fixture_snapshot["route_policy"]["tier_upgrades"] = {"interaction.history": "protected"}
    fixture_snapshot["route_policy"]["on_unresolved_instruction"] = "refuse"
    add(fixture_snapshot, "conversation", turn())
    add(fixture_snapshot, "policy-registry", {**next(b for b in fixture_snapshot["batches"] if b["producer"]["id"] == "policy-registry")["items"][0],
                                              "id": "policy:v13", "body": "Never refund."})
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "instruction", "items": ["policy:v12", "policy:v13"]}]
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert [c["resolution"] for c in result.trace["conflicts"]] == ["refused"]
    assert result.trace["refused"]["reason"] == "protected_slot_unplaced"
