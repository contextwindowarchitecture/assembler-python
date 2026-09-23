"""Renderers turn placed occurrences into the exact payload bytes that are hashed (R-21)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

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


def place(profile: Profile, items: Iterable[Item]) -> tuple[Occurrence, ...]:
    """One occurrence per item per placement of its slot, in profile order and by id within a placement."""
    by_id = sorted(items, key=lambda item: item.id)
    return tuple(
        Occurrence(position, placement.slot, placement.wrap, item)
        for position, placement in enumerate(profile.placement)
        for item in by_id if item.slot == placement.slot
    )


class Renderer(Protocol):
    id: str

    def profile_errors(self, profile: Profile) -> list[str]:
        """Why this renderer cannot realize the profile; empty when it can."""
        ...

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered: ...


REGISTRY: dict[str, Renderer] = {r.id: r for r in (FixtureXml(),)}
