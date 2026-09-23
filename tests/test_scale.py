"""DESIGN.md §7: tokenizer calls grow linearly with the number of items, with or without budget pressure.

Timings depend on the machine, so scripts/bench.py reports them; this pins the call counts, which do not.
Characters tokenized still grow quadratically under heavy shedding, because each fit test counts the whole
payload (§7 records the numbers).
"""
from __future__ import annotations

import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from bench import BUDGETS, measure  # noqa: E402


@pytest.mark.parametrize("n", [50, 100, 200])
def test_tokenizer_calls_grow_linearly(n):
    fits, tight = measure(n, BUDGETS["fits"]), measure(n, BUDGETS["tight"])
    assert fits["omitted"] == 0 and tight["omitted"] >= n - 5  # the tight budget sheds nearly everything
    assert fits["calls"] <= 2 * n + 10
    assert tight["calls"] <= 4 * n + 10
