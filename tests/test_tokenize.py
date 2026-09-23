"""Tokenizers (conformance/README.md, Tokenizers and renderers): what the declared tokenizer counts (R-16)."""
from __future__ import annotations

import pytest

from cwa.tokenize import REGISTRY


@pytest.mark.parametrize("text, count", [
    ("", 0),
    ("abcd", 1),
    ("abcde", 2),
    ("é", 1),        # 2 bytes
    ("例例", 2),      # 3 bytes each: 6 bytes
    ("😀", 1),       # 4 bytes; one code point, two UTF-16 code units
    ("😀a", 2),      # 5 bytes
    (" " * 4, 3),  # 12 bytes: whitespace counts like any other byte
])
def test_estimate_utf8_counts_utf8_bytes_divided_by_four_rounded_up(text, count):
    assert REGISTRY["estimate-utf8/v1"].count(text) == count


class Characters:
    """A caller's tokenizer: any object with an id and a count."""
    id = "caller-characters/v1"

    def count(self, text: str) -> int:
        return len(text)


def test_the_package_exports_the_tokenizer_protocol():
    from cwa import Tokenizer

    assert isinstance(Characters(), Tokenizer)
    assert all(isinstance(t, Tokenizer) for t in REGISTRY.values())


def test_a_caller_tokenizer_counts_the_payload_and_names_itself_in_the_trace(fixture_snapshot):
    from cwa import Snapshot, assemble

    fixture_snapshot["tokenizer"] = Characters.id
    result = assemble(Snapshot.freeze(**fixture_snapshot, tokenizers={Characters.id: Characters()}))
    assert result.trace["context"]["tokenizer"] == Characters.id
    assert result.trace["result"]["input_tokens"] == len(result.payload.decode())


def test_caller_tokenizers_join_the_built_in_ones_and_leave_no_trace_behind(fixture_snapshot):
    from cwa import Snapshot, SnapshotError

    extra = {Characters.id: Characters()}
    assert Snapshot.from_json(fixture_snapshot, tokenizers=extra).tokenizer.id == "fixture-whitespace/v1"
    fixture_snapshot["tokenizer"] = Characters.id
    assert Snapshot.from_json(fixture_snapshot, tokenizers=extra).tokenizer.id == Characters.id
    with pytest.raises(SnapshotError, match="unknown tokenizer 'caller-characters/v1'"):
        Snapshot.from_json(fixture_snapshot)  # no registry the first call could have changed


@pytest.mark.parametrize("built_in", ["fixture-whitespace/v1", "estimate-utf8/v1"])
def test_a_caller_cannot_redefine_a_built_in_tokenizer(fixture_snapshot, built_in):
    """A published id must count as conformance/README.md defines it, whoever supplies the object."""
    from cwa import Snapshot

    with pytest.raises(ValueError, match=f"{built_in} is built in"):
        Snapshot.from_json(fixture_snapshot, tokenizers={built_in: Characters()})
