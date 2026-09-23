"""M0 refuses to guess. Each case here becomes real behavior in a later milestone."""
import pytest

from cwa import Snapshot, assemble


def test_unplaced_slot_waits_for_placement_checks(fixture_snapshot):
    fixture_snapshot["profile"]["placement"].pop(1)
    with pytest.raises(NotImplementedError, match="M4"):
        assemble(Snapshot.from_json(fixture_snapshot))


def test_peer_instructions_wait_for_conflict_policy(fixture_snapshot):
    peer = {**fixture_snapshot["batches"][0]["items"][0], "id": "policy:v13"}
    fixture_snapshot["batches"][0]["items"].append(peer)
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "instruction", "items": ["policy:v12", "policy:v13"]}]
    with pytest.raises(NotImplementedError, match="M3"):
        assemble(Snapshot.from_json(fixture_snapshot))


def test_fact_groups_wait_for_fact_policy(fixture_snapshot):
    fixture_snapshot["route_policy"]["facts"] = {"refund.window": {"precedence": ["policy-corpus"], "on_unresolved": "surface"}}
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "fact", "fact": "refund.window", "items": ["policy:v12", "turn:18"]}]
    with pytest.raises(NotImplementedError, match="M3"):
        assemble(Snapshot.from_json(fixture_snapshot))
