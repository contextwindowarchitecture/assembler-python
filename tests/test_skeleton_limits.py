"""M0 refuses to guess. Each case here becomes real behavior in a later milestone."""
import pytest

from cwa import Snapshot, assemble


def test_over_budget_waits_for_fitting(fixture_snapshot):
    fixture_snapshot["budget"]["input"] = 10
    with pytest.raises(NotImplementedError, match="M2"):
        assemble(Snapshot.from_json(fixture_snapshot))


def test_unplaced_slot_waits_for_admission(fixture_snapshot):
    fixture_snapshot["profile"]["placement"].pop(1)
    with pytest.raises(NotImplementedError, match="M1"):
        assemble(Snapshot.from_json(fixture_snapshot))


def test_conflicts_wait_for_resolution(fixture_snapshot):
    fixture_snapshot["conflicts"] = [{"id": "g1", "kind": "instruction", "items": ["policy:v12", "turn:18"]}]
    with pytest.raises(NotImplementedError, match="M3"):
        assemble(Snapshot.from_json(fixture_snapshot))
