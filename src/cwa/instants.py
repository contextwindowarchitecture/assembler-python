"""RFC 3339 instants compared at their full stated precision (R-2), in the portable profile of
conformance/README.md, Timestamps: ASCII digits, no leap seconds, nothing after the offset.

A float or datetime would round beyond microseconds; this keeps whole seconds and the fractional
digits exactly as written, and needs no clock.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_INSTANT = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})[Tt]([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(?:\.([0-9]+))?"
                      r"([Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def _parse(text: str) -> tuple[int, str]:
    match = _INSTANT.fullmatch(text)
    if not match:
        raise ValueError(f"not a portable RFC 3339 date-time: {text!r}")
    date, hour, minute, second, fraction, offset = match.groups()
    zone = "+00:00" if offset in ("Z", "z") else offset
    moment = datetime.fromisoformat(f"{date}T{hour}:{minute}:{second}{zone}")
    return int((moment - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()), fraction or ""


def compare(a: str, b: str, *, b_offset_seconds: int = 0) -> int:
    """-1, 0 or 1 as instant a is before, equal to, or after instant b shifted by b_offset_seconds."""
    (sa, fa), (sb, fb) = _parse(a), _parse(b)
    sb += b_offset_seconds
    if sa != sb:
        return -1 if sa < sb else 1
    width = max(len(fa), len(fb))
    fa, fb = fa.ljust(width, "0"), fb.ljust(width, "0")
    return 0 if fa == fb else -1 if fa < fb else 1
