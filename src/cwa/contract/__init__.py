"""The vendored CWA contract: schemas, slot defaults and reason codes, pinned by contract.lock.json."""
from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_DATA = files(__package__) / "data"

POLICY_FIELDS = ("token_budget", "variants", "conflict_policy", "lineage", "eligibility", "injection_risk")


def load(name: str) -> Any:
    return json.loads((_DATA / name).read_text(encoding="utf-8"))


@cache
def _registry() -> Registry:
    schemas = [load(f"schema/{entry.name}") for entry in (_DATA / "schema").iterdir() if entry.name.endswith(".schema.json")]
    return Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)


@cache
def validator(name: str) -> Draft202012Validator:
    """Validator for schema/<name>.schema.json with format checking enabled."""
    return Draft202012Validator(
        load(f"schema/{name}.schema.json"),
        registry=_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def errors(name: str, document: Any) -> list[str]:
    """Schema errors as stable, human-readable strings; empty when valid."""
    found = sorted(validator(name).iter_errors(document), key=lambda e: (list(e.absolute_path), e.message))
    return [f"/{'/'.join(map(str, e.absolute_path))} {e.message}" for e in found]


SLOT_DEFAULTS: dict[str, dict[str, Any]] = load("slot-defaults.json")
REASONS: dict[str, dict[str, Any]] = {reason["code"]: reason for reason in load("reasons.json")}
