from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..canonical import canonical_json
from .fixture_xml import TAG, escape_attribute, escape_body

if TYPE_CHECKING:
    from . import Occurrence, Rendered
    from ..model import Profile

_CHANNELS = ("system", "tools")


@dataclass(frozen=True, slots=True)
class Request:
    """The parts of a cwa-messages/v1 request, before its user message is assembled."""
    channels: dict[str, list[dict[str, Any]]]
    """The system and tools entries, {"id", "text"} and "conflict" for a surfaced member, in occurrence order."""
    message: tuple[dict[str, Any], ...]
    """One entry per xml: occurrence, in order: its id, the text cwa-messages/v1 writes for it into the user message,
    and "conflict" for a surfaced member."""
    bodies: tuple[str, ...]
    """Each occurrence's rendered body, in order, for per-item token attribution."""

    @property
    def channel_texts(self) -> tuple[str, ...]:
        return tuple(entry["text"] for name in _CHANNELS for entry in self.channels[name])


def request(occurrences: tuple[Occurrence, ...]) -> Request:
    """Render each occurrence as cwa-messages/v1 does: governance in the platform's system and tools channels, and every
    other occurrence, prior turns included, as escaped material for the one user message (R-7, R-10, R-11)."""
    channels: dict[str, list[dict[str, Any]]] = {name: [] for name in _CHANNELS}
    message, bodies = [], []
    for occurrence in occurrences:
        item, mark = occurrence.item, {"conflict": occurrence.conflict} if occurrence.conflict else {}
        if occurrence.wrap in _CHANNELS:
            # Only verified governance with no injection risk reaches these slots (R-10). The model
            # sees only an entry's text, so a surfaced member's mark goes inside it (R-11).
            body = item.body
            text = f'<conflict group="{escape_attribute(occurrence.conflict)}">\n{body}\n</conflict>' if occurrence.conflict else body
            channels[occurrence.wrap].append({"id": item.id, **mark, "text": text})
        else:
            body, tag = escape_body(item.body), occurrence.wrap.removeprefix("xml:")
            attributes = f' id="{escape_attribute(item.id)}"'
            if occurrence.slot == "interaction.history":
                attributes += f' speaker="{"assistant" if item.lineage == "generated" else "user"}"'
            if occurrence.conflict:
                attributes += f' conflict="{escape_attribute(occurrence.conflict)}"'
            message.append({"id": item.id, **mark, "text": f"<{tag}{attributes}>\n{body}\n</{tag}>\n"})
        bodies.append(body)
    return Request(channels=channels, message=tuple(message), bodies=tuple(bodies))


class Messages:
    """The render IR of D-1: RFC 8785 JSON of {messages, system, tools}.

    Governance may take the platform's system and tools channels; every other occurrence, prior
    turns included, is escaped material in the one user message, whose query is the live user turn
    (R-7, R-10). The payload's size is the sum of its texts' counts (R-16).
    """

    id = "cwa-messages/v1"

    def profile_errors(self, profile: Profile) -> list[str]:
        problems, seen_xml = [], False
        for index, placement in enumerate(profile.placement):
            wrap, slot = placement.wrap, placement.slot
            if wrap not in _CHANNELS and not (wrap.startswith("xml:") and TAG.fullmatch(wrap.removeprefix("xml:"))):
                problems.append(f"placement[{index}] wrap {wrap!r} is not system, tools or xml:<name>")
            elif wrap == "system" and not slot.startswith("governance."):
                problems.append(f"placement[{index}] puts {slot} in system; only governance slots take a platform role")
            elif wrap == "tools" and slot != "governance.capabilities":
                problems.append(f"placement[{index}] puts {slot} in tools; only governance.capabilities does")
            elif wrap == "system" and seen_xml:
                problems.append(f"placement[{index}] puts system after an xml: placement, which a message request cannot realize")
            seen_xml = seen_xml or wrap.startswith("xml:")
        return problems

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered:
        from . import Rendered

        parts = request(occurrences)
        content = "".join(entry["text"] for entry in parts.message)
        document = {"messages": [{"role": "user", "content": content}], **parts.channels}
        return Rendered(payload=canonical_json(document), bodies=parts.bodies, texts=parts.channel_texts + (content,))
