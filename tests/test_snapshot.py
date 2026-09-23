import pytest

from cwa import Snapshot, SnapshotError, assemble


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


def _unplace(slot: str):
    def mutate(snapshot: dict) -> None:
        snapshot["profile"]["placement"] = [p for p in snapshot["profile"]["placement"] if p["slot"] != slot] + [
            {"slot": "state.user", "wrap": "xml:state.user"}]
    return mutate


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["profile"].update(route="other-route"), "profile is for route 'other-route', the route policy for 'contract-fixture'"),
    (_unplace("governance.instructions"), "profile does not place governance.instructions"),
    (_unplace("interaction.query"), "profile does not place interaction.query"),
    (lambda s: s["route_policy"].update(parser=True), "profile does not place governance.output_contract, which the parser route requires"),
])
def test_profiles_that_cannot_carry_the_route_are_rejected_before_assembly(fixture_snapshot, mutate, message):
    """R-20: a profile places instructions and query, and the output contract on a parser route,
    and it names the route policy it was built for."""
    mutate(fixture_snapshot)
    with pytest.raises(SnapshotError, match=message):
        Snapshot.from_json(fixture_snapshot)


def test_a_parser_route_accepts_a_profile_that_places_the_output_contract(fixture_snapshot):
    fixture_snapshot["route_policy"]["parser"] = True
    fixture_snapshot["profile"]["placement"].insert(1, {"slot": "governance.output_contract", "wrap": "xml:format"})
    Snapshot.from_json(fixture_snapshot)


def test_snapshot_is_detached_from_the_callers_document(fixture_snapshot):
    snapshot = Snapshot.from_json(fixture_snapshot)
    before = snapshot.digest()
    fixture_snapshot["batches"][0]["items"][0]["body"] = "changed after freezing"
    assert snapshot.digest() == before
    assert snapshot.to_json() == Snapshot.from_json(snapshot.to_json()).to_json()


def test_freeze_is_the_keyword_form_of_from_json(fixture_snapshot):
    assert Snapshot.freeze(**fixture_snapshot).digest() == Snapshot.from_json(fixture_snapshot).digest()


# R-11: conflict groups must agree with the snapshot, or it is rejected before assembly.

def group(id: str, *items: str, fact: str | None = None) -> dict:
    return {"id": id, "kind": "fact" if fact else "instruction", "items": list(items), **({"fact": fact} if fact else {})}


@pytest.mark.parametrize("groups, message", [
    ([group("g1", "policy:v12", "nobody")], "conflict group g1 names 'nobody', which is not a candidate"),
    ([group("g1", "policy:v12", "turn:18"), group("g2", "turn:18", "refunds-eu:v17#p4")], "'turn:18' belongs to more than one conflict group"),
    ([group("g1", "policy:v12", "turn:18"), group("g1", "refunds-eu:v17#p4", "memory:expired")], "conflict group ids repeat: g1"),
    ([group("g1", "refunds-eu:v17#p4", "memory:expired", fact="refund.window")], "fact 'refund.window', which the route policy does not define"),
])
def test_conflict_groups_must_agree_with_the_snapshot(fixture_snapshot, groups, message):
    fixture_snapshot["conflicts"] = groups
    with pytest.raises(SnapshotError, match=message):
        Snapshot.from_json(fixture_snapshot)


def test_conflict_groups_may_name_producer_exclusions_and_defined_facts(fixture_snapshot):
    fixture_snapshot["route_policy"]["facts"] = {"refund.window": {"precedence": ["policy-corpus"], "on_unresolved": "surface"}}
    fixture_snapshot["conflicts"] = [group("g1", "refunds-eu:v17#p4", "memory:expired", fact="refund.window")]
    Snapshot.from_json(fixture_snapshot)


def test_the_order_a_group_lists_its_items_does_not_change_the_snapshot(fixture_snapshot):
    fixture_snapshot["conflicts"] = [group("g1", "turn:18", "policy:v12")]
    listed = Snapshot.from_json(fixture_snapshot)
    fixture_snapshot["conflicts"] = [group("g1", "policy:v12", "turn:18")]
    assert listed.digest() == Snapshot.from_json(fixture_snapshot).digest()
    assert listed.conflicts[0].items == ("policy:v12", "turn:18")


def test_candidates_sharing_an_id_do_not_make_the_digest_order_dependent(fixture_snapshot):
    """R-23: the replay key cannot depend on the order a producer returned duplicates in."""
    corpus = fixture_snapshot["batches"][1]
    first, second = dict(corpus["items"][0], body="one body"), dict(corpus["items"][0], body="another body")
    corpus["items"] = [first, second]
    corpus["excluded"] = [{"item_id": "kb:x", "reason": "below_threshold", "stage": "producer"},
                          {"item_id": "kb:x", "reason": "expired", "stage": "producer"}]
    listed = Snapshot.from_json(fixture_snapshot).digest()
    corpus["items"].reverse()
    corpus["excluded"].reverse()
    assert Snapshot.from_json(fixture_snapshot).digest() == listed


def test_producer_rows_order_by_producer_then_item_in_utf16_code_units(fixture_snapshot):
    """conformance/README.md, Ordering: U+1F600 is D83D DE00 in UTF-16, so it sorts before U+FF5A."""
    fixture_snapshot["batches"] += [
        {"producer": {"id": "wiki-\uff5a", "kind": "retrieval"}, "items": [], "excluded": [
            {"item_id": "w:\uff5a", "reason": "stale", "stage": "producer"}, {"item_id": "w:\U0001f600", "reason": "stale", "stage": "producer"}]},
        {"producer": {"id": "wiki-\U0001f600", "kind": "retrieval"}, "items": [], "excluded": [
            {"item_id": "v:1", "reason": "stale", "stage": "producer"}]},
    ]
    rows = [row["item_id"] for row in assemble(Snapshot.from_json(fixture_snapshot)).trace["excluded"] if row["stage"] == "producer"]
    assert rows == ["memory:expired", "v:1", "w:\U0001f600", "w:\uff5a"]
