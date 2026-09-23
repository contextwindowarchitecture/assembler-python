import pytest

from cwa import Snapshot, SnapshotError


@pytest.mark.parametrize("bad", ["yesterday", "2026-02-30T12:00:00Z", "2026-09-22T12:00:00"])
def test_timestamps_are_format_checked(fixture_snapshot, bad):
    fixture_snapshot["assembly_time"] = bad
    with pytest.raises(SnapshotError, match="assembly_time"):
        Snapshot.from_json(fixture_snapshot)


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s.update(tokenizer="gpt-guess/v0"), "unknown tokenizer"),
    (lambda s: s.update(renderer="nope/v1"), "unknown renderer"),
    (lambda s: s["profile"]["placement"][0].update(wrap="system"), "not an xml:<name> wrap"),
    (lambda s: s["route_policy"].update(version="fixture/v2"), "profile expects route policy"),
    (lambda s: s["batches"][1]["producer"].update(id="policy-registry"), "more than one batch"),
    (lambda s: s["batches"][0]["producer"].update(kind="self-declared"), "kind"),
    (lambda s: s.update(clock="now"), "Additional properties"),
])
def test_unassemblable_snapshots_are_rejected_before_assembly(fixture_snapshot, mutate, message):
    mutate(fixture_snapshot)
    with pytest.raises(SnapshotError, match=message):
        Snapshot.from_json(fixture_snapshot)


def test_snapshot_is_detached_from_the_callers_document(fixture_snapshot):
    snapshot = Snapshot.from_json(fixture_snapshot)
    before = snapshot.digest()
    fixture_snapshot["batches"][0]["items"][0]["body"] = "changed after freezing"
    assert snapshot.digest() == before
    assert snapshot.to_json() == Snapshot.from_json(snapshot.to_json()).to_json()


def test_freeze_is_the_keyword_form_of_from_json(fixture_snapshot):
    assert Snapshot.freeze(**fixture_snapshot).digest() == Snapshot.from_json(fixture_snapshot).digest()
