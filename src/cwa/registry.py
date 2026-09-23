"""The registry: profiles and route policies pinned by digest in a lock (conformance/README.md, Registry).

It works before snapshots are built: an application loads its profiles and route policies against
the lock, and passes what the registry returns into Snapshot.freeze. Content cannot change under an
unchanged version, except for a profile's evaluation (R-20), and a deployment gets only evaluated
profiles (R-19).
"""
from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

from . import contract
from .canonical import digest

Document = Mapping[str, Any]
_KINDS = (("profiles", "profile", "id"), ("route_policies", "route policy", "route"))


class RegistryError(ValueError):
    """Content that the lock does not pin, or a request the registry cannot honor."""

    def __init__(self, problems: list[str]):
        super().__init__("registry:\n  " + "\n  ".join(problems))
        self.problems = problems


def profile_digest(profile: Document) -> str:
    """SHA-256 of the RFC 8785 form without evaluation, so evaluation alone keeps the version (R-20)."""
    return digest({key: value for key, value in profile.items() if key != "evaluation"})


def route_policy_digest(policy: Document) -> str:
    return digest(policy)


def _label(noun: str, name: str, version: Any) -> str:
    return f"{noun} {name} v{version}" if noun == "profile" else f"{noun} {name} {version}"


def _identities(profiles: Iterable[Document], route_policies: Iterable[Document]) -> tuple[dict, list[str]]:
    """{(kind, name, version): (document, digest)} for valid documents, and the problems found."""
    found, problems = {}, []
    for (key, noun, name), schema, documents, measure in (
            (_KINDS[0], "profile", profiles, profile_digest), (_KINDS[1], "route_policy", route_policies, route_policy_digest)):
        for index, document in enumerate(documents):
            if errors := contract.errors(schema, document):
                problems += [f"{noun} {index}: {error}" for error in errors]
                continue
            identity, measured = (key, document[name], document["version"]), measure(document)
            if found.get(identity, (None, measured))[1] != measured:
                problems.append(f"{_label(noun, *identity[1:])} is given twice with different content")
            found[identity] = (copy.deepcopy(dict(document)), measured)
    return found, problems


def _pins(lock: Document) -> dict:
    """{(kind, name, version): digest}. Raises on an invalid lock or an identity listed twice."""
    if problems := [f"lock: {error}" for error in contract.errors("registry_lock", lock)]:
        raise RegistryError(problems)
    pins, problems = {}, []
    for key, noun, name in _KINDS:
        for entry in lock[key]:
            identity = (key, entry[name], entry["version"])
            if identity in pins:
                problems.append(f"the lock lists {_label(noun, entry[name], entry['version'])} more than once")
            pins[identity] = entry["sha256"]
    if problems:
        raise RegistryError(sorted(set(problems)))
    return pins


def _noun(key: str) -> str:
    return next(noun for k, noun, _ in _KINDS if k == key)


def lock(profiles: Iterable[Document] = (), route_policies: Iterable[Document] = (), *, existing: Document | None = None) -> dict:
    """A lock pinning the given content: existing entries, plus one for each identity not yet pinned.
    Content whose identity is pinned with another digest is refused; its version must increase."""
    pins = _pins(existing) if existing is not None else {}
    found, problems = _identities(profiles, route_policies)
    for identity, (_, measured) in sorted(found.items(), key=lambda entry: entry[0]):
        if pins.setdefault(identity, measured) != measured:
            problems.append(f"{_label(_noun(identity[0]), *identity[1:])} is already pinned with another digest; increase its version")
    if problems:
        raise RegistryError(problems)
    return {key: [{name: n, "version": v, "sha256": pins[(k, n, v)]} for (k, n, v) in sorted(pins) if k == key]
            for key, _, name in _KINDS}


class Registry:
    def __init__(self, content: Mapping[tuple, Document]):
        self._content = content

    @classmethod
    def from_json(cls, lock: Document, profiles: Iterable[Document], route_policies: Iterable[Document]) -> Registry:
        """Load content against the lock. Everything must be valid and pinned with its own digest."""
        pins = _pins(lock)
        found, problems = _identities(profiles, route_policies)
        for identity, (_, measured) in sorted(found.items(), key=lambda entry: entry[0]):
            label = _label(_noun(identity[0]), *identity[1:])
            if identity not in pins:
                problems.append(f"{label} is not in the lock")
            elif pins[identity] != measured:
                problems.append(f"{label} differs from its lock entry: it changed without a version increase (R-20)")
        if problems:
            raise RegistryError(problems)
        return cls({identity: document for identity, (document, _) in found.items()})

    def _get(self, key: str, name: str, version: Any) -> dict:
        if (key, name, version) not in self._content:
            raise RegistryError([f"no {_label(_noun(key), name, version)} in the registry"])
        return copy.deepcopy(dict(self._content[(key, name, version)]))

    def profile(self, id: str, version: int, *, deployment: bool = False) -> dict:
        """A copy of the pinned profile. A deployment accepts only an evaluated one (R-19), for which
        the profile schema requires a model family and a complete evaluation."""
        profile = self._get("profiles", id, version)
        if deployment and profile["evaluation"]["status"] != "evaluated":
            raise RegistryError([f"{_label('profile', id, version)} is unevaluated; a deployment needs an evaluated profile (R-19)"])
        return profile

    def route_policy(self, route: str, version: str) -> dict:
        return self._get("route_policies", route, version)
