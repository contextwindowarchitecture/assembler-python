from __future__ import annotations

import re

from ..strings import WHITESPACE

# Runs outside the ECMAScript whitespace set, so counts match JavaScript's /\S+/gu.
_TOKEN = re.compile(f"[^{WHITESPACE}]+")


class FixtureWhitespace:
    """Counts runs of non-whitespace. A test fixture, not a model tokenizer."""

    id = "fixture-whitespace/v1"

    def count(self, text: str) -> int:
        return len(_TOKEN.findall(text))
