"""Blank strings follow ECMAScript whitespace, not Python's (R-2; conformance/README.md, Blank strings)."""
import pytest

from cwa.strings import blank

ECMASCRIPT_WHITESPACE = [*"\t\n\v\f\r   ", *map(chr, range(0x2000, 0x200B)), *"    　﻿"]


@pytest.mark.parametrize("char", ECMASCRIPT_WHITESPACE, ids=lambda c: f"U+{ord(c):04X}")
def test_ecmascript_whitespace_is_blank(char):
    assert blank(char) and blank(" " + char + "\n")


@pytest.mark.parametrize("char", ["\x1c", "\x1d", "\x1e", "\x1f", "\x85", "​", "a"], ids=lambda c: f"U+{ord(c):04X}")
def test_characters_python_or_unicode_call_space_are_not_blank(char):
    assert not blank(char)
