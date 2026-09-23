"""M0 refuses to guess. Each case here becomes real behavior in a later milestone."""
import pytest

from cwa import Snapshot, assemble


def test_unplaced_slot_waits_for_placement_checks(fixture_snapshot):
    fixture_snapshot["profile"]["placement"].pop(1)
    with pytest.raises(NotImplementedError, match="M4"):
        assemble(Snapshot.from_json(fixture_snapshot))

