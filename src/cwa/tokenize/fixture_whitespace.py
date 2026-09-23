from __future__ import annotations

import re

# ECMAScript WhiteSpace + LineTerminator, so counts match JavaScript's /\S+/gu. Python's own \S
# differs at U+001C..U+001F and U+FEFF (conformance/README.md).
_TOKEN = re.compile(r"[^\t\n\v\f\r    -     　﻿]+")


class FixtureWhitespace:
    """Counts runs of non-whitespace. A test fixture, not a model tokenizer."""

    id = "fixture-whitespace/v1"
    exact = True
    margin = 0.0

    def count(self, text: str) -> int:
        return len(_TOKEN.findall(text))
