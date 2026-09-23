"""Admission: every candidate is admitted or excluded with exactly one registered reason."""
from __future__ import annotations

import copy

import pytest

from cwa import Snapshot, assemble

KNOWLEDGE = 1  # batch index of policy-corpus in the fixture snapshot after normalization


def knowledge(**fields) -> dict:
    item = {"id": "kb:x", "slot": "evidence.knowledge", "source": "policy-corpus", "source_version": "1",
            "authority": "reference_only", "trust": "verified", "freshness": "2026-09-12T15:30:00Z",
            "relevance": 0.9, "scope": {"tenant": "acme"}, "body": "A passage."}
    item.update(fields)
    return {k: v for k, v in item.items() if v is not None}


def add(snapshot: dict, producer: str, *items: dict) -> dict:
    batch = next(b for b in snapshot["batches"] if b["producer"]["id"] == producer)
    batch["items"].extend(copy.deepcopy(items))
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
