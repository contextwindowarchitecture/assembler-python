"""RFC 8785 (JSON Canonicalization Scheme) serialization, for digests that match across languages."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from .strings import utf16


def canonical_json(value: Any) -> bytes:
    return _encode(value).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=utf16)
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _encode(value[k]) for k in keys) + "}"
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


def _number(value: float) -> str:
    """Format like ECMAScript Number.prototype.toString, which JCS requires."""
    if not math.isfinite(value):
        raise ValueError("JSON has no NaN or Infinity")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    _, digit_tuple, exponent = Decimal(repr(abs(value))).as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0")
    exponent += len("".join(map(str, digit_tuple))) - len(digits)
    k, n = len(digits), exponent + len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + digits
    e = n - 1
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
