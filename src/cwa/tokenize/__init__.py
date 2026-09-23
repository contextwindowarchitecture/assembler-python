"""Tokenizers count rendered text. The built-in ones are conformance/README.md's; callers pass their own to
Snapshot.from_json or Snapshot.freeze. An estimating tokenizer's headroom is the snapshot's budget.margin_percent (R-16)."""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from .estimate_utf8 import EstimateUtf8
from .fixture_whitespace import FixtureWhitespace


@runtime_checkable
class Tokenizer(Protocol):
    """Any object with an id, which a snapshot's tokenizer field names, and a count of a text's tokens."""

    id: str

    def count(self, text: str) -> int: ...


REGISTRY: Mapping[str, Tokenizer] = {t.id: t for t in (FixtureWhitespace(), EstimateUtf8())}
