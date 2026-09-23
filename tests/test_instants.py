import pytest

from cwa import instants


@pytest.mark.parametrize("a, b, expected", [
    ("2026-09-22T12:00:00Z", "2026-09-22T12:00:00.000Z", 0),
    ("2026-09-22T14:00:00+02:00", "2026-09-22T12:00:00Z", 0),
    ("2026-09-22T12:00:00.0005Z", "2026-09-22T12:00:00Z", 1),
    ("2026-09-22T11:59:59.999999999Z", "2026-09-22T12:00:00Z", -1),
    ("2026-09-22T12:00:00.123456789012Z", "2026-09-22T12:00:00.123456789011Z", 1),
    ("2016-12-31T23:59:60Z", "2017-01-01T00:00:00Z", 0),
])
def test_compares_beyond_microseconds(a, b, expected):
    assert instants.compare(a, b) == expected


def test_offset_shifts_the_second_instant():
    assert instants.compare("2026-09-22T12:00:05Z", "2026-09-22T12:00:00Z", b_offset_seconds=5) == 0
