"""The published fixture, stated literally so a changed case file cannot silently move the target."""
from cwa import Snapshot, assemble


def test_fixture_payload_hash_and_tokens(fixture_snapshot):
    result = assemble(Snapshot.from_json(fixture_snapshot))
    assert result.trace["result"] == {
        "input_tokens": 34,
        "hash": "4cf0b083e167bb952c1ba0f9a93bf3ed3c64b178c063c259b49cdace1b86972f",
    }
    assert [row["tokens"] for row in result.trace["included"]] == [9, 10, 6]


def test_assembly_is_repeatable(fixture_snapshot):
    first = assemble(Snapshot.from_json(fixture_snapshot), trace_id="t")
    assert assemble(Snapshot.from_json(fixture_snapshot), trace_id="t") == first


def test_defaults_filled_are_traced_as_records(fixture_snapshot):
    query = fixture_snapshot["batches"][3]["items"][0]
    for field in ("lineage", "eligibility"):
        del query[field]
    trace = assemble(Snapshot.from_json(fixture_snapshot)).trace
    assert trace["defaults_filled"] == [{"item_id": "turn:18", "field": "lineage"}, {"item_id": "turn:18", "field": "eligibility"}]


def test_included_rows_record_eligibility_after_defaults_are_filled(fixture_snapshot):
    """R-22: each included occurrence names its eligibility; a filled value is the route's override
    when there is one (R-3), else the slot default."""
    query = fixture_snapshot["batches"][3]["items"][0]
    del query["eligibility"]
    fixture_snapshot["route_policy"]["default_overrides"] = {"interaction.query": {"eligibility": "support-chat/v1: live turn"}}
    rows = {row["item_id"]: row["eligibility"] for row in assemble(Snapshot.from_json(fixture_snapshot)).trace["included"]}
    assert rows["turn:18"] == "support-chat/v1: live turn"
    del fixture_snapshot["route_policy"]["default_overrides"]
    rows = {row["item_id"]: row["eligibility"] for row in assemble(Snapshot.from_json(fixture_snapshot)).trace["included"]}
    assert rows == {"policy:v12": "route-policy", "refunds-eu:v17#p4": "support-chat/v1: tenant acme; rerank at least 0.82", "turn:18": "route-policy"}
