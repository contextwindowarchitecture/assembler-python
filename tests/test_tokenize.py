"""Tokenizers (conformance/README.md, Tokenizers and renderers): what the declared tokenizer counts (R-16)."""
from __future__ import annotations

import pytest

from conftest import published
from cwa.tokenize import REGISTRY

PUBLISHED = published("counts")


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
    from cwa import Snapshot, UnsupportedComponentError

    extra = {Characters.id: Characters()}
    assert Snapshot.from_json(fixture_snapshot, tokenizers=extra).tokenizer.id == "fixture-whitespace/v1"
    fixture_snapshot["tokenizer"] = Characters.id
    assert Snapshot.from_json(fixture_snapshot, tokenizers=extra).tokenizer.id == Characters.id
    with pytest.raises(UnsupportedComponentError, match="does not provide the tokenizer 'caller-characters/v1'"):
        Snapshot.from_json(fixture_snapshot)  # no registry the first call could have changed


def test_the_built_in_tokenizers_are_the_published_ones():
    """R-16 stops on a caller's tokenizer under a published id, and the check below compares with the built-in
    ids, so they must be exactly the ones conformance/README.md lists. A tokenizer published later fails this."""
    assert set(PUBLISHED) == set(REGISTRY)


@pytest.mark.parametrize("entry", ["from_json", "freeze"])
@pytest.mark.parametrize("built_in", PUBLISHED)
def test_a_caller_cannot_redefine_a_built_in_tokenizer(fixture_snapshot, built_in, entry):
    """R-16: a published id must count as conformance/README.md defines it, whoever supplies the object. Either
    entry point raises before a Snapshot exists, so assembly never starts: no payload and no trace."""
    from cwa import Snapshot

    load = {"from_json": lambda **kw: Snapshot.from_json(fixture_snapshot, **kw),
            "freeze": lambda **kw: Snapshot.freeze(**fixture_snapshot, **kw)}[entry]
    with pytest.raises(ValueError, match=f"{built_in} is built in"):
        load(tokenizers={built_in: Characters()})


class Named:
    """A caller's tokenizer that calls itself whatever it is given."""

    def __init__(self, id: str) -> None:
        self.id = id

    def count(self, text: str) -> int:
        return len(text)


@pytest.mark.parametrize("entry", ["from_json", "freeze"])
@pytest.mark.parametrize("own_id", [*PUBLISHED, "caller-other/v1"])
def test_a_caller_tokenizer_is_accepted_only_under_its_own_id(fixture_snapshot, own_id, entry):
    """R-16: the trace names the tokenizer by its own id. Under another key, one that calls itself a published
    tokenizer would put that id in the trace beside the caller's count, and any other would name a tokenizer the
    snapshot does not declare. Either entry point raises before a Snapshot exists: no payload and no trace."""
    from cwa import Snapshot

    fixture_snapshot["tokenizer"] = "caller/v1"
    load = {"from_json": lambda **kw: Snapshot.from_json(fixture_snapshot, **kw),
            "freeze": lambda **kw: Snapshot.freeze(**fixture_snapshot, **kw)}[entry]
    with pytest.raises(ValueError, match=f"'caller/v1' calls itself '{own_id}'"):
        load(tokenizers={"caller/v1": Named(own_id)})
