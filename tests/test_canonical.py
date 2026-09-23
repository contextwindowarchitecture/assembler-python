import pytest

from cwa.canonical import canonical_json


@pytest.mark.parametrize("value, text", [
    (0.91, "0.91"), (100.0, "100"), (-0.0, "0"), (1e21, "1e+21"), (1e20, "100000000000000000000"),
    (1e-7, "1e-7"), (0.000001, "0.000001"), (123.456e-10, "1.23456e-8"), (-2.5, "-2.5"), (5e-324, "5e-324"),
])
def test_numbers_format_like_ecmascript(value, text):
    assert canonical_json(value) == text.encode()


def test_keys_sort_by_utf16_code_units_rfc8785():
    # The RFC 8785 section 3.2.3 example: U+1F600 sorts before U+FB33 in UTF-16, after it in code points.
    keys = ["€", "\r", "דּ", "1", "\U0001F600", "\u0080", "ö"]
    encoded = canonical_json({k: 0 for k in keys}).decode()
    order = sorted(keys, key=lambda k: encoded.index('"' + k + '"' if k != "\r" else '"\\r"'))
    assert order == ["\r", "1", "\u0080", "ö", "€", "\U0001F600", "דּ"]


def test_structure_has_no_insignificant_whitespace():
    assert canonical_json({"b": [1, True, None], "a": "x"}) == b'{"a":"x","b":[1,true,null]}'
