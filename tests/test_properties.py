"""Properties over generated snapshots (docs/DESIGN.md §6), where the conformance cases fix single
examples: input order never matters (R-23), protected bytes never change (R-16, R-17), droppable
items go before any compressible item is reduced under budget pressure (R-16), the payload fits its
budget and counts its items (R-16, R-21), every capped slot fits its max_tokens (R-16), a
deduplicated slot includes each key once (R-24), a superseding slot keeps only the latest of each
call (R-25), refusals have no payload (R-17), and a stored snapshot replays (R-23)."""
from __future__ import annotations

import copy
import hashlib

from hypothesis import HealthCheck, assume, given, settings, strategies as st

from cwa import Snapshot, assemble
from cwa import instants
from cwa.dedupe import key
from cwa.render.fixture_xml import escape_body
from cwa.tokenize.fixture_whitespace import FixtureWhitespace
from conftest import CASES, read_json

TEMPLATE = read_json(CASES / "budget-variant-choice" / "snapshot.json")
PRODUCER = {"governance.instructions": "policy-registry", "governance.examples": "policy-registry", "state.task": "state-svc",
            "evidence.knowledge": "policy-corpus", "interaction.history": "conversation", "interaction.query": "conversation"}
KIND = {"policy-registry": "policy", "state-svc": "state", "policy-corpus": "retrieval", "conversation": "interaction"}
AUTHORITY = {"governance.instructions": "governing", "governance.examples": "governing", "state.task": "state",
             "evidence.knowledge": "reference_only", "interaction.history": "user", "interaction.query": "user"}
PROTECTED = ("governance.instructions", "state.task", "interaction.query")
DROPPABLE = ("governance.examples",)
COMPRESSIBLE = ("evidence.knowledge", "interaction.history")
# All before assembly_time (2026-09-22T12:00:00Z) and within the route's age limit for state.
FRESHNESS = ["2026-09-22T11:59:00Z", "2026-09-22T11:59:30Z", "2026-09-22T11:59:30.000001Z", "2026-09-22T11:59:59Z"]
count = FixtureWhitespace().count

# Words that escaping, counting and ordering must all survive.
words = st.sampled_from(["refund", "Pro", "30", "days", "<b>", "&amp;", 'say "yes"', "é", "\U0001f600", "ｚ", "a&b<c>"])
bodies = st.lists(words, min_size=1, max_size=10).map(" ".join) | st.sampled_from(
    ["refund Pro", " refund  Pro", "refund\tPro\u3000", "refund\u200bPro", "Refund Pro"])  # equal keys, and near misses
suffixes = st.sampled_from(["", "a", "ｚ", "\U0001f600", "#p4"])


@st.composite
def items(draw, slot: str, index: int) -> dict:
    item_id = f"{slot.split('.')[1]}:{index}{draw(suffixes)}"
    item = {"id": item_id, "slot": slot, "source": draw(st.sampled_from(["src:" + item_id, "crm:order/42", "crm:order/43"])), "source_version": "1", "authority": AUTHORITY[slot],
            "trust": "verified" if slot.startswith("governance.") else "unverified", "freshness": draw(st.sampled_from(FRESHNESS)),
            "body": draw(bodies)}
    if slot == "evidence.knowledge":
        item.update(scope={"tenant": "acme"}, relevance=draw(st.floats(0.5, 1.0)))
    if slot in COMPRESSIBLE:
        item["variants"] = [{"id": f"{item_id}~{n}", "body": draw(bodies), "method": "extract", "lineage": "extracted"}
                            for n in range(draw(st.integers(0, 2)))]
    return item


@st.composite
def snapshots(draw) -> dict:
    counts = {"governance.instructions": 1, "interaction.query": 1, "state.task": draw(st.integers(0, 1)),
              "governance.examples": draw(st.integers(0, 3)), "evidence.knowledge": draw(st.integers(0, 4)),
              "interaction.history": draw(st.integers(0, 3))}
    candidates = [draw(items(slot, n)) for slot, k in counts.items() for n in range(k)]
    snapshot = copy.deepcopy(TEMPLATE)
    policy = snapshot["route_policy"]
    for slot in DROPPABLE + COMPRESSIBLE:
        rules = policy.setdefault("slots", {}).setdefault(slot, {})
        rules["priority"] = draw(st.integers(-1, 1))
        rules["order_by"] = draw(st.sampled_from([["-relevance", "-freshness"], ["-freshness"], ["freshness"]]))
    if draw(st.booleans()):
        for slot in ("state.task",) + DROPPABLE + COMPRESSIBLE:
            if (cap := draw(st.none() | st.integers(0, 30))) is not None:
                policy.setdefault("slots", {}).setdefault(slot, {})["max_tokens"] = cap
    for slot in PROTECTED + DROPPABLE + COMPRESSIBLE:
        if draw(st.booleans()):
            policy.setdefault("slots", {}).setdefault(slot, {})["dedupe"] = "exact"
        if draw(st.booleans()):
            policy.setdefault("slots", {}).setdefault(slot, {})["supersede"] = "source"
    steps = [{"slot": slot, "action": action} for slot in COMPRESSIBLE for action in ("compress", "omit")]
    policy["fitting_order"] = draw(st.lists(st.sampled_from(steps), unique_by=lambda s: (s["slot"], s["action"]), max_size=3))
    snapshot["renderer"] = draw(st.sampled_from(["fixture-xml/v1", "cwa-messages/v1"]))
    snapshot["budget"]["input"] = draw(st.integers(20, 110))
    snapshot["batches"] = [{"producer": {"id": p, "kind": KIND[p]}, "items": [c for c in candidates if PRODUCER[c["slot"]] == p], "excluded": []}
                           for p in sorted(KIND)]
    return snapshot


def _outcome(document: dict) -> tuple:
    snapshot = Snapshot.from_json(document)
    result = assemble(snapshot, trace_id="t")
    return result.payload, result.trace, snapshot.digest()


def _rows(trace: dict, reason: str) -> set[str]:
    return {row["item_id"] for row in trace["excluded"] if row["reason"] == reason}


def _candidates(document: dict, slots: tuple[str, ...]) -> list[dict]:
    return [c for b in document["batches"] for c in b["items"] if c["slot"] in slots]


def _slot_caps(document: dict) -> dict[str, int]:
    return {slot: rules["max_tokens"] for slot, rules in document["route_policy"].get("slots", {}).items() if "max_tokens" in rules}


PROPERTY = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@PROPERTY
@given(snapshots())
def test_generated_snapshots_admit_every_candidate(document):
    """The generator's own check: every property below starts from items admission accepts."""
    trace = assemble(Snapshot.from_json(document)).trace
    assert {row["reason"] for row in trace["excluded"]} <= {"over_budget", "superseded", "duplicate_content"}


@PROPERTY
@given(snapshots(), st.randoms(use_true_random=False))
def test_input_order_never_changes_the_outcome(document, rng):
    shuffled = copy.deepcopy(document)
    rng.shuffle(shuffled["batches"])
    for batch in shuffled["batches"]:
        rng.shuffle(batch["items"])
    assert _outcome(shuffled) == _outcome(document)


@PROPERTY
@given(snapshots())
def test_protected_bytes_never_change(document):
    result = assemble(Snapshot.from_json(document))
    protected = {c["id"]: c for c in _candidates(document, PROTECTED)}
    assert not protected.keys() & (_rows(result.trace, "over_budget") | {row["item_id"] for row in result.trace["compressed"]})
    if not result.refused:
        included = {row["item_id"]: row["tokens"] for row in result.trace["included"]}
        for item_id, item in protected.items():
            assert included[item_id] == count(escape_body(item["body"]))


@PROPERTY
@given(snapshots())
def test_droppable_items_go_before_any_compressible_item_is_reduced(document):
    """Under budget pressure alone: a slot cap sheds only its own slot, so a capped route may compress
    one slot's items while another slot keeps its droppable ones."""
    assume(not _slot_caps(document))
    trace = assemble(Snapshot.from_json(document)).trace
    compressible = {c["id"] for c in _candidates(document, COMPRESSIBLE)}
    reduced = compressible & (_rows(trace, "over_budget") | {row["item_id"] for row in trace["compressed"]})
    if reduced:  # a droppable item may already be gone as a duplicate (R-24)
        gone = _rows(trace, "over_budget") | _rows(trace, "superseded") | _rows(trace, "duplicate_content")
        assert {c["id"] for c in _candidates(document, DROPPABLE)} <= gone


@PROPERTY
@given(snapshots())
def test_included_tokens_fit_within_the_payload_and_the_payload_within_the_budget(document):
    result = assemble(Snapshot.from_json(document))
    if not result.refused:
        assert sum(row["tokens"] for row in result.trace["included"]) <= result.trace["result"]["input_tokens"] <= document["budget"]["input"]


@PROPERTY
@given(snapshots())
def test_every_capped_slot_fits_its_max_tokens(document):
    result = assemble(Snapshot.from_json(document))
    if not result.refused:
        for slot, cap in _slot_caps(document).items():
            assert sum(row["tokens"] for row in result.trace["included"] if row["slot"] == slot) <= cap


@PROPERTY
@given(snapshots())
def test_a_deduplicated_slot_includes_each_key_once_and_names_a_kept_copy(document):
    """The generator declares no conflict groups, so only protected items are exempt."""
    trace = assemble(Snapshot.from_json(document)).trace
    bodies = {c["id"]: c["body"] for c in _candidates(document, PROTECTED + DROPPABLE + COMPRESSIBLE)}
    superseded = _rows(trace, "superseded")
    duplicates = {row["item_id"] for row in trace["excluded"] if row["reason"] == "duplicate_content"}
    for row in trace["excluded"]:
        if row["reason"] == "duplicate_content":  # the kept copy may still be omitted later, for budget
            assert row["slot"] not in PROTECTED and row["duplicate_of"] not in duplicates
            assert key(bodies[row["item_id"]]) == key(bodies[row["duplicate_of"]])
    for slot, rules in document["route_policy"].get("slots", {}).items():
        if rules.get("dedupe") == "exact" and slot not in PROTECTED:
            keys = [key(bodies[row["item_id"]]) for row in trace["included"] if row["slot"] == slot]
            assert len(keys) == len(set(keys))
            assert not superseded & {row["duplicate_of"] for row in trace["excluded"] if row["reason"] == "duplicate_content"}


@PROPERTY
@given(snapshots())
def test_a_superseding_slot_keeps_only_the_latest_of_each_call(document):
    """Each producer emits its own slots here, so a call is a slot and a source. Only protected items are exempt."""
    trace = assemble(Snapshot.from_json(document)).trace
    expected = {}
    for slot, rules in document["route_policy"].get("slots", {}).items():
        if rules.get("supersede") != "source" or slot in PROTECTED:
            continue
        for item in (c for c in _candidates(document, (slot,))):
            call = [c for c in _candidates(document, (slot,)) if c["source"] == item["source"]]
            if any(instants.compare(item["freshness"], c["freshness"]) < 0 for c in call):
                expected[item["id"]] = item["source"]
    rows = {row["item_id"]: row["superseded_by"] for row in trace["excluded"] if row["reason"] == "superseded"}
    assert rows.keys() == expected.keys()
    sources = {c["id"]: c["source"] for b in document["batches"] for c in b["items"]}
    assert all(sources[kept] == expected[item_id] and kept not in rows for item_id, kept in rows.items())


@PROPERTY
@given(snapshots())
def test_a_refusal_has_no_payload_and_a_payload_carries_its_hash(document):
    result = assemble(Snapshot.from_json(document))
    trace = result.trace
    if result.refused:
        assert result.payload is None and trace["result"] is None and trace["included"] == trace["compressed"] == []
    else:
        assert trace["result"]["hash"] == hashlib.sha256(result.payload).hexdigest()


@PROPERTY
@given(snapshots())
def test_a_stored_snapshot_replays_to_the_same_outcome(document):
    stored = Snapshot.from_json(document).to_json()
    assert _outcome(stored) == _outcome(document)
