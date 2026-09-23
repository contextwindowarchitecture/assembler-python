"""The registry (conformance/README.md, Registry): profiles and route policies pinned by digest.

Content cannot change under an unchanged version (R-20), except for a profile's evaluation, and a
deployment gets only evaluated profiles (R-19). The registry works before snapshots are built.
"""
from __future__ import annotations

import copy

import pytest

from cwa.registry import Registry, RegistryError, lock, profile_digest, route_policy_digest
from conftest import ROOT, read_json

REGISTRY = ROOT / "conformance" / "registry"
EVALUATED = {"status": "evaluated", "suite": "support-evals/1", "date": "2026-09-20", "result": "pass 94/100",
             "artifact": "https://example.org/runs/1"}


@pytest.fixture
def published() -> tuple[dict, list[dict], list[dict]]:
    return (read_json(REGISTRY / "lock.json"), read_json(REGISTRY / "profiles.json"), read_json(REGISTRY / "route-policies.json"))


def test_digests_agree_with_the_published_lock(published):
    """The website computes these digests in JavaScript; the same bytes must come out here."""
    pinned, profiles, policies = published
    assert [{"id": p["id"], "version": p["version"], "sha256": profile_digest(p)} for p in profiles] == pinned["profiles"]
    assert [{"route": p["route"], "version": p["version"], "sha256": route_policy_digest(p)} for p in policies] == pinned["route_policies"]


def test_a_registry_returns_pinned_content_by_identity(published):
    registry = Registry.from_json(*published)
    profile = registry.profile("document-analysis", 3)
    assert profile == published[1][1]
    profile["placement"].clear()
    assert registry.profile("document-analysis", 3) == published[1][1]
    assert registry.route_policy("contract-fixture", "fixture/v1") == published[2][0]


@pytest.mark.parametrize("change", [
    lambda p: p["placement"].reverse(),
    lambda p: p["placement"][0].update(wrap="xml:instructions"),
    lambda p: p.update(model_family="example-model/1"),
    lambda p: p.update(route_policy_version="illustrative/v3"),
])
def test_a_profile_changed_under_an_unchanged_version_is_refused(published, change):
    pinned, profiles, policies = published
    change(profiles[0])
    with pytest.raises(RegistryError, match="profile policy-first-chat v2 differs from its lock entry"):
        Registry.from_json(pinned, profiles, policies)


def test_a_route_policy_changed_under_an_unchanged_version_is_refused(published):
    pinned, profiles, policies = published
    policies[0]["clock_skew_seconds"] = 5
    with pytest.raises(RegistryError, match="route policy contract-fixture fixture/v1 differs from its lock entry"):
        Registry.from_json(pinned, profiles, policies)


def test_an_evaluation_alone_keeps_the_version(published):
    """R-20: promoting an identical payload configuration may keep its version."""
    pinned, profiles, policies = published
    draft = {**copy.deepcopy(profiles[0]), "version": 3, "model_family": "example-model/1"}
    pinned = lock([draft], existing=pinned)
    promoted = {**draft, "evaluation": EVALUATED}
    assert Registry.from_json(pinned, profiles + [promoted], policies).profile("policy-first-chat", 3, deployment=True) == promoted


def test_a_deployment_gets_only_evaluated_profiles(published):
    registry = Registry.from_json(*published)
    registry.profile("policy-first-chat", 2)
    with pytest.raises(RegistryError, match="profile policy-first-chat v2 is unevaluated; a deployment needs an evaluated profile"):
        registry.profile("policy-first-chat", 2, deployment=True)


@pytest.mark.parametrize("mutate, message", [
    (lambda lk, pr, po: pr.append({**pr[0], "version": 9}), "profile policy-first-chat v9 is not in the lock"),
    (lambda lk, pr, po: lk["profiles"].append(dict(lk["profiles"][0])), "the lock lists profile policy-first-chat v2 more than once"),
    (lambda lk, pr, po: lk["route_policies"].append(dict(lk["route_policies"][0])), "the lock lists route policy contract-fixture fixture/v1 more than once"),
    (lambda lk, pr, po: lk["profiles"][0].update(sha256="ABC"), "lock: /profiles/0/sha256"),
    (lambda lk, pr, po: pr.insert(0, {**pr[0], "placement": pr[0]["placement"][::-1]}),
     "profile policy-first-chat v2 is given twice with different content"),
    (lambda lk, pr, po: pr[0].pop("evaluation"), "profile 0: "),
    (lambda lk, pr, po: po[0].pop("producers"), "route policy 0: "),
])
def test_invalid_or_unpinned_content_is_refused(published, mutate, message):
    mutate(*published)
    with pytest.raises(RegistryError, match=message):
        Registry.from_json(*published)


def test_asking_for_content_the_registry_lacks_is_refused(published):
    registry = Registry.from_json(*published)
    with pytest.raises(RegistryError, match="no profile policy-first-chat v1 in the registry"):
        registry.profile("policy-first-chat", 1)
    with pytest.raises(RegistryError, match="no route policy support-chat v9 in the registry"):
        registry.route_policy("support-chat", "v9")


def test_locking_adds_new_identities_and_never_rewrites_one(published):
    pinned, profiles, policies = published
    bumped = {**copy.deepcopy(profiles[0]), "version": 3, "placement": profiles[0]["placement"][::-1]}
    grown = lock([bumped], existing=pinned)
    assert {"id": "policy-first-chat", "version": 3, "sha256": profile_digest(bumped)} in grown["profiles"]
    assert all(entry in grown["profiles"] for entry in pinned["profiles"])
    assert lock(profiles, policies) == lock(list(reversed(profiles)), list(reversed(policies)))
    edited = {**bumped, "version": 2}
    with pytest.raises(RegistryError, match="profile policy-first-chat v2 is already pinned with another digest; increase its version"):
        lock([edited], existing=pinned)


@pytest.mark.parametrize("missing", ["artifact", "suite", "result"])
def test_an_evaluation_without_its_artifact_or_run_is_not_an_evaluation(published, missing):
    """R-19: descriptive results without a reproducible artifact do not count as validation."""
    pinned, profiles, policies = published
    profiles[0] = {**profiles[0], "model_family": "example-model/1", "evaluation": {**EVALUATED, missing: None}}
    with pytest.raises(RegistryError, match="profile 0: "):
        Registry.from_json(pinned, profiles, policies)


def test_what_the_registry_returns_is_what_a_snapshot_carries(published, fixture_snapshot):
    from cwa import Snapshot, assemble

    registry = Registry.from_json(*published)
    fixture_snapshot.update(profile=registry.profile("fixture-three-slot", 1), route_policy=registry.route_policy("contract-fixture", "fixture/v1"))
    assert assemble(Snapshot.freeze(**fixture_snapshot)).payload == (ROOT / "conformance/cases/fixture-three-slot/expected.payload.txt").read_bytes()
