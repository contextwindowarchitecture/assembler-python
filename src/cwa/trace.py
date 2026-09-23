"""Trace validation against the published schema (R-21)."""
from __future__ import annotations

from typing import Any

from . import contract


class TraceError(ValueError):
    pass


def validate(trace: dict[str, Any]) -> None:
    if problems := contract.errors("trace", trace):
        raise TraceError("trace does not match trace.schema.json:\n  " + "\n  ".join(problems))
