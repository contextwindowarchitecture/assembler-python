"""String rules every implementation must evaluate alike (conformance/README.md, Blank strings)."""
from __future__ import annotations

import re

# ECMAScript WhiteSpace and LineTerminator, the set JavaScript's \s matches. Python's own \s differs
# at U+001C..U+001F and U+FEFF, so the set is spelled out.
WHITESPACE = "\t\n\v\f\r    -     　﻿"
_NONBLANK = re.compile(f"[^{WHITESPACE}]")


def blank(value: str) -> bool:
    """True when every character is ECMAScript whitespace or a line terminator."""
    return not _NONBLANK.search(value)
