"""Renderers turn placed occurrences into the exact payload bytes that are hashed (R-21). The built-in ones are
conformance/README.md's; callers pass their own to Snapshot.from_json or Snapshot.freeze (R-16)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Iterable, Mapping, Protocol

from .. import instants
from ..strings import utf16
from ..model import Item, Profile
from ..tokenize import Tokenizer
from .fixture_xml import FixtureXml
from .messages import Messages

HISTORY = "interaction.history"


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


def _said_order(a: Item, b: Item) -> int:
    """Prior turns in the order they were said: by freshness, compared as instants at full precision, and by id only
    among turns said at the same instant (R-7)."""
    if said := instants.compare(a.freshness, b.freshness):
        return said
    ka, kb = utf16(a.id), utf16(b.id)
    return (ka > kb) - (ka < kb)


def _render_order(slot: str, items: Iterable[Item]) -> list[Item]:
    """A placement's items in render order: by id, except interaction.history, whose turns go in the order they were
    said (R-7; conformance/README.md, Ordering)."""
    if slot == HISTORY:
        return sorted(items, key=cmp_to_key(_said_order))
    return sorted(items, key=lambda item: utf16(item.id))


def place(profile: Profile, items: Iterable[Item], marks: Mapping[str, str] | None = None) -> tuple[Occurrence, ...]:
    """One occurrence per item per placement of its slot, in profile order and, within a placement, in render order.
    marks maps the id of each surfaced conflict member to its group id."""
    items, marks = tuple(items), marks or {}
    ordered = {slot: _render_order(slot, (item for item in items if item.slot == slot))
               for slot in dict.fromkeys(placement.slot for placement in profile.placement)}
    return tuple(
        Occurrence(position, placement.slot, placement.wrap, item, marks.get(item.id))
        for position, placement in enumerate(profile.placement)
        for item in ordered[placement.slot]
    )


class Renderer(Protocol):
    id: str

    def profile_errors(self, profile: Profile) -> list[str]:
        """Why this renderer cannot realize the profile; empty when it can."""
        ...

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered: ...


# conformance/README.md, Tokenizers and renderers: every implementation provides REQUIRED, and its Optional list adds
# the rest of PUBLISHED. R-16 stops on a caller's renderer under any published id, whether it is built in here or not.
# tests/test_render.py pins both to the README's bullets.
REQUIRED = ("fixture-xml/v1", "cwa-messages/v1")
PUBLISHED = (*REQUIRED, "cwa-message-blocks/v1")
REGISTRY: dict[str, Renderer] = {r.id: r for r in (FixtureXml(), Messages())}
