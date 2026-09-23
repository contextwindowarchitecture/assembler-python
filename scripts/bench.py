"""Measure assemble() against DESIGN.md §7's expectations: time, tokenizer calls and characters tokenized.

    uv run python scripts/bench.py

Snapshots are fixture-three-slot's with n retrieved passages. "fits" gives an unlimited budget, so
nothing sheds; "tight" gives 60 tokens, so fitting omits nearly every passage, one fit test at a time.
Timings depend on the machine and stay out of the suite; tests/test_scale.py pins the call counts.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SIZES = (10, 100, 500)
BUDGETS = {"fits": 10**9, "tight": 60}


class CountingTokenizer:
    """Counts whitespace-separated words, and how often and how much it was asked to count."""

    id = "bench-counting/v1"

    def __init__(self) -> None:
        self.calls = 0
        self.characters = 0

    def count(self, text: str) -> int:
        self.calls += 1
        self.characters += len(text)
        return len(text.split())


def snapshot(n: int, budget: int) -> dict[str, Any]:
    """fixture-three-slot's snapshot with n retrieved passages in place of its one, counted by CountingTokenizer."""
    document = json.loads((ROOT / "conformance/cases/fixture-three-slot/snapshot.json").read_text(encoding="utf-8"))
    corpus = next(b for b in document["batches"] if b["producer"]["id"] == "policy-corpus")
    template = corpus["items"][0]
    corpus["items"] = [
        {**copy.deepcopy(template), "id": f"kb:{i:04d}", "source": f"doc:{i}", "relevance": 0.5 + (i % 50) / 100,
         "body": f"Passage {i} about refunds within thirty days of purchase for plan tier {i % 7}."}
        for i in range(n)]
    document["budget"]["input"] = budget
    document["tokenizer"] = CountingTokenizer.id
    return document


def measure(n: int, budget: int) -> dict[str, Any]:
    from cwa import Snapshot, assemble

    tokenizer = CountingTokenizer()
    frozen = Snapshot.from_json(snapshot(n, budget), tokenizers={tokenizer.id: tokenizer})
    start = time.perf_counter()
    result = assemble(frozen)
    elapsed = (time.perf_counter() - start) * 1000
    omitted = sum(1 for row in result.trace["excluded"] if row["reason"] == "over_budget")
    return {"calls": tokenizer.calls, "characters": tokenizer.characters, "omitted": omitted, "ms": elapsed}


def main() -> None:
    print("| Items | Budget | Omitted | Tokenizer calls | Characters tokenized | Time (ms) |")
    print("|---:|---|---:|---:|---:|---:|")
    for n in SIZES:
        for label, budget in BUDGETS.items():
            m = measure(n, budget)
            print(f"| {n} | {label} | {m['omitted']} | {m['calls']:,} | {m['characters']:,} | {m['ms']:.1f} |")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    main()
