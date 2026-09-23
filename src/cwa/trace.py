"""Trace validation against the published schema and reason registry (R-21)."""
from __future__ import annotations

from typing import Any

from . import contract


class TraceError(ValueError):
    pass


def _registered(reason: str, kind: str) -> bool:
    field = reason.removeprefix("missing_field:")
    code = "missing_field:<name>" if field and field != reason else reason
    return contract.REASONS.get(code, {}).get("kind") == kind


def _unregistered(trace: dict[str, Any]) -> list[str]:
    # Producer rows carry what the producer reported; the assembler's own codes come from the registry.
    problems = [f"/excluded {row['item_id']}: {row['reason']} is not a registered exclusion code"
                for row in trace["excluded"] if row["stage"] == "assembler" and not _registered(row["reason"], "exclusion")]
    if trace["refused"]["bool"] and not _registered(trace["refused"]["reason"], "refusal"):
        problems.append(f"/refused {trace['refused']['reason']} is not a registered refusal code")
    return problems


def validate(trace: dict[str, Any]) -> None:
    if problems := contract.errors("trace", trace) or _unregistered(trace):
        raise TraceError("trace does not match trace.schema.json and contract/reasons.json:\n  " + "\n  ".join(problems))
