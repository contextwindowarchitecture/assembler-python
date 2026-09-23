"""The examples/ tokenizer adapters satisfy cwa.Tokenizer without their libraries installed (R-16, R-23)."""
from __future__ import annotations

import sys

from cwa import Snapshot, Tokenizer, assemble
from conftest import ROOT

sys.path.insert(0, str(ROOT / "examples"))
from tiktoken_tokenizer import TiktokenTokenizer  # noqa: E402


class FakeEncoding:
    """Stands in for tiktoken.Encoding: one token per character, and special-token text refused unless allowed."""
    name = "fake_base"

    def encode(self, text: str, *, disallowed_special="all") -> list[int]:
        if disallowed_special == "all" and "<|endoftext|>" in text:
            raise ValueError("special token")
        return [ord(c) for c in text]


def test_the_adapter_is_a_tokenizer_named_after_its_encoding():
    tokenizer = TiktokenTokenizer(FakeEncoding())
    assert isinstance(tokenizer, Tokenizer)
    assert tokenizer.id == "tiktoken-fake_base/v1"
    assert TiktokenTokenizer(FakeEncoding(), id="mine/v1").id == "mine/v1"


def test_special_token_text_in_a_body_counts_as_ordinary_text():
    """Bodies are untrusted: a body that spells a special token must be counted, not crash assembly."""
    assert TiktokenTokenizer(FakeEncoding()).count("hi <|endoftext|>") == len("hi <|endoftext|>")


def test_the_adapter_counts_an_assembly(fixture_snapshot):
    tokenizer = TiktokenTokenizer(FakeEncoding())
    fixture_snapshot["tokenizer"] = tokenizer.id
    result = assemble(Snapshot.from_json(fixture_snapshot, tokenizers={tokenizer.id: tokenizer}))
    assert result.trace["result"]["input_tokens"] == len(result.payload.decode())
