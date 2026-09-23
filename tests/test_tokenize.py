"""Tokenizers (conformance/README.md, Tokenizers and renderers): what the declared tokenizer counts (R-16)."""
from __future__ import annotations

import pytest

from cwa.tokenize import REGISTRY


@pytest.mark.parametrize("text, count", [
    ("", 0),
    ("abcd", 1),
    ("abcde", 2),
    ("é", 1),        # 2 bytes
    ("例例", 2),      # 3 bytes each: 6 bytes
    ("😀", 1),       # 4 bytes; one code point, two UTF-16 code units
    ("😀a", 2),      # 5 bytes
    (" " * 4, 3),  # 12 bytes: whitespace counts like any other byte
])
def test_estimate_utf8_counts_utf8_bytes_divided_by_four_rounded_up(text, count):
    assert REGISTRY["estimate-utf8/v1"].count(text) == count
