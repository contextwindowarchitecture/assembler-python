from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..canonical import canonical_json
from .fixture_xml import TAG, escape_attribute, escape_body

if TYPE_CHECKING:
    from . import Occurrence, Rendered
    from ..model import Profile

_CHANNELS = ("system", "tools")


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

        channels: dict[str, list[dict[str, Any]]] = {name: [] for name in _CHANNELS}
        bodies, parts = [], []
        for occurrence in occurrences:
            item = occurrence.item
            if occurrence.wrap in _CHANNELS:
                # Only verified governance with no injection risk reaches these slots (R-10). The model
                # sees only an entry's text, so a surfaced member's mark goes inside it (R-11).
                body = item.body
                entry = {"id": item.id, "text": body}
                if occurrence.conflict:
                    group = occurrence.conflict
                    entry = {**entry, "conflict": group, "text": f'<conflict group="{escape_attribute(group)}">\n{body}\n</conflict>'}
                channels[occurrence.wrap].append(entry)
            else:
                body, tag = escape_body(item.body), occurrence.wrap.removeprefix("xml:")
                attributes = f' id="{escape_attribute(item.id)}"'
                if occurrence.slot == "interaction.history":
                    attributes += f' speaker="{"assistant" if item.lineage == "generated" else "user"}"'
                if occurrence.conflict:
                    attributes += f' conflict="{escape_attribute(occurrence.conflict)}"'
                parts.append(f"<{tag}{attributes}>\n{body}\n</{tag}>\n")
            bodies.append(body)
        content = "".join(parts)
        document = {"messages": [{"role": "user", "content": content}], **channels}
        texts = tuple(entry["text"] for name in _CHANNELS for entry in channels[name]) + (content,)
        return Rendered(payload=canonical_json(document), bodies=tuple(bodies), texts=texts)
