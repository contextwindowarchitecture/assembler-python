"""The published fixture, stated literally so a changed case file cannot silently move the target."""
from cwa import Snapshot, assemble


def test_fixture_payload_hash_and_tokens(fixture_snapshot):
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert result.trace["result"] == {
        "input_tokens": 34,
        "hash": "4cf0b083e167bb952c1ba0f9a93bf3ed3c64b178c063c259b49cdace1b86972f",
    }
    assert [row["tokens"] for row in result.trace["included"]] == [9, 10, 6]


def test_assembly_is_repeatable_and_input_order_does_not_matter(fixture_snapshot):
    first = assemble(Snapshot.from_json(fixture_snapshot), trace_id="t")
    fixture_snapshot["batches"].reverse()
    fixture_snapshot["batches"][1]["items"].reverse()
    second = assemble(Snapshot.from_json(fixture_snapshot), trace_id="t")
    assert first.payload == second.payload
    assert first.trace == second.trace
    assert first.trace["context"]["snapshot_digest"] == second.trace["context"]["snapshot_digest"]


def test_defaults_filled_are_traced_as_records(fixture_snapshot):
    query = fixture_snapshot["batches"][3]["items"][0]
    for field in ("lineage", "eligibility"):
        del query[field]
    trace = assemble(Snapshot.from_json(fixture_snapshot)).trace
    assert trace["defaults_filled"] == [{"item_id": "turn:18", "field": "lineage"}, {"item_id": "turn:18", "field": "eligibility"}]
