"""String rules every implementation must evaluate alike (conformance/README.md: Blank strings, Ordering)."""
from __future__ import annotations

import re

# ECMAScript WhiteSpace and LineTerminator, the set JavaScript's \s matches. Python's own \s differs
# at U+001C..U+001F and U+FEFF, so the set is spelled out.
WHITESPACE = "\t\n\v\f\r    -     　﻿"
_NONBLANK = re.compile(f"[^{WHITESPACE}]")


def blank(value: str) -> bool:
    """True when every character is ECMAScript whitespace or a line terminator."""
    return not _NONBLANK.search(value)


def utf16(value: str) -> bytes:
    """Sort key that orders strings by UTF-16 code units, as RFC 8785 orders member names. Every
    string ordering in the spec uses it."""
    return value.encode("utf-16-be")
