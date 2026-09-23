"""Renderers turn placed occurrences into the exact payload bytes that are hashed (R-21)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from ..strings import utf16
from ..model import Item, Profile
from ..tokenize import Tokenizer
from .fixture_xml import FixtureXml
from .messages import Messages


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One rendered appearance of an item. A slot placed twice yields two occurrences (R-16)."""
    position: int
    slot: str
    wrap: str
    item: Item
    conflict: str | None = None
    """The surfaced conflict group the item belongs to, which the renderer marks (R-11)."""


@dataclass(frozen=True, slots=True)
class Rendered:
    payload: bytes
    bodies: tuple[str, ...]
    """Each occurrence's rendered body, in order, for per-item token attribution."""
    texts: tuple[str, ...]
    """The texts the tokenizer counts; the payload's size is the sum of their counts."""

    def tokens(self, tokenizer: Tokenizer) -> int:
        return sum(tokenizer.count(text) for text in self.texts)


def place(profile: Profile, items: Iterable[Item], marks: Mapping[str, str] | None = None) -> tuple[Occurrence, ...]:
    """One occurrence per item per placement of its slot, in profile order and by id within a placement.
    marks maps the id of each surfaced conflict member to its group id."""
    by_id, marks = sorted(items, key=lambda item: utf16(item.id)), marks or {}
    return tuple(
        Occurrence(position, placement.slot, placement.wrap, item, marks.get(item.id))
        for position, placement in enumerate(profile.placement)
        for item in by_id if item.slot == placement.slot
    )


class Renderer(Protocol):
    id: str

    def profile_errors(self, profile: Profile) -> list[str]:
        """Why this renderer cannot realize the profile; empty when it can."""
        ...

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered: ...


REGISTRY: dict[str, Renderer] = {r.id: r for r in (FixtureXml(), Messages())}
