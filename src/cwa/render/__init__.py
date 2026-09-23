"""Renderers turn placed occurrences into the exact payload bytes that are hashed (R-21)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..model import Item, Profile
from .fixture_xml import FixtureXml


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One rendered appearance of an item. A slot placed twice yields two occurrences (R-16)."""
    position: int
    slot: str
    wrap: str
    item: Item


@dataclass(frozen=True, slots=True)
class Rendered:
    payload: bytes
    bodies: tuple[str, ...]
    """Each occurrence's rendered body, in order, for per-item token attribution."""


class Renderer(Protocol):
    id: str

    def profile_errors(self, profile: Profile) -> list[str]:
        """Why this renderer cannot realize the profile; empty when it can."""
        ...

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered: ...


REGISTRY: dict[str, Renderer] = {r.id: r for r in (FixtureXml(),)}
