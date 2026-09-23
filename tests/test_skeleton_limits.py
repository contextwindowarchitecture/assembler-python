"""M0 refuses to guess. Each case here becomes real behavior in a later milestone."""
import pytest

from cwa import Snapshot, assemble


def test_unplaced_slot_waits_for_placement_checks(fixture_snapshot):
    fixture_snapshot["profile"]["placement"].pop(1)
    with pytest.raises(NotImplementedError, match="M4"):
        assemble(Snapshot.from_json(fixture_snapshot))


def test_fact_groups_wait_for_fact_policy(fixture_snapshot):
    fixture_snapshot["route_policy"]["facts"] = {"refund.window": {"precedence": ["policy-corpus"], "on_unresolved": "surface"}}
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "fact", "fact": "refund.window", "items": ["policy:v12", "turn:18"]}]
    with pytest.raises(NotImplementedError, match="M3"):
        assemble(Snapshot.from_json(fixture_snapshot))
