from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Occurrence, Rendered
    from ..model import Profile

TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


def escape_body(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attribute(text: str) -> str:
    return escape_body(text).replace('"', "&quot;")


class FixtureXml:
    """The conformance fixture renderer: one XML-style element per occurrence, bodies escaped (R-7, R-10)."""

    id = "fixture-xml/v1"

    def profile_errors(self, profile: Profile) -> list[str]:
        problems = []
        for index, placement in enumerate(profile.placement):
            tag = placement.wrap.removeprefix("xml:")
            if not placement.wrap.startswith("xml:") or not TAG.match(tag):
                problems.append(f"placement[{index}] wrap {placement.wrap!r} is not an xml:<name> wrap")
        return problems

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered:
        from . import Rendered

        bodies = tuple(escape_body(o.item.body) for o in occurrences)
        parts = []
        for occurrence, body in zip(occurrences, bodies):
            tag = occurrence.wrap.removeprefix("xml:")
            conflict = f' conflict="{escape_attribute(occurrence.conflict)}"' if occurrence.conflict else ""
            parts.append(f'<{tag} id="{escape_attribute(occurrence.item.id)}"{conflict}>\n{body}\n</{tag}>\n')
        text = "".join(parts)
        return Rendered(payload=text.encode("utf-8"), bodies=bodies, texts=(text,))
