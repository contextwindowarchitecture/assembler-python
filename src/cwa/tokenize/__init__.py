"""Tokenizers count rendered text. Each declares whether its count is exact for its target model."""
from __future__ import annotations

from typing import Protocol

from .fixture_whitespace import FixtureWhitespace


class Tokenizer(Protocol):
    id: str
    exact: bool
    margin: float
    """Fractional safety margin an estimator adds; 0 for exact tokenizers (DESIGN.md D-3)."""

    def count(self, text: str) -> int: ...


REGISTRY: dict[str, Tokenizer] = {t.id: t for t in (FixtureWhitespace(),)}
