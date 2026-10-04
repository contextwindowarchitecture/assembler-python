from __future__ import annotations

from typing import TYPE_CHECKING

from ..canonical import canonical_json
from .messages import Messages, request

if TYPE_CHECKING:
    from . import Occurrence, Rendered


class MessageBlocks(Messages):
    """cwa-message-blocks/v1, an optional renderer (conformance/README.md, Tokenizers and renderers, Optional): the
    request cwa-messages/v1 renders, except that the one user message's content is an array with one entry per xml:
    occurrence, in order, so an application can put a provider's cache breakpoint at any item boundary.

    An entry is {"id", "text"}, with "conflict" for a surfaced member, and its text is exactly what cwa-messages/v1
    writes for that occurrence, so the joined texts are that renderer's content. The entries are parts of the one user
    message, never messages of their own (R-7). It realizes exactly the profiles cwa-messages/v1 realizes, and its size
    is the sum of every system, tool and message entry's count, each text counted on its own (R-16).
    """

    id = "cwa-message-blocks/v1"

    def render(self, occurrences: tuple[Occurrence, ...]) -> Rendered:
        from . import Rendered

        parts = request(occurrences)
        document = {"messages": [{"role": "user", "content": list(parts.message)}], **parts.channels}
        texts = parts.channel_texts + tuple(entry["text"] for entry in parts.message)
        return Rendered(payload=canonical_json(document), bodies=parts.bodies, texts=texts)
