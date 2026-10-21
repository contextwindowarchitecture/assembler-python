"""The examples/ run as the README shows them.

The tokenizer adapters satisfy cwa.Tokenizer without their libraries installed (R-16, R-23). The quickstart the README
mirrors admits relevant evidence and leaves out the rest (R-13), renders governance apart from untrusted material
(R-7, R-10), and refuses when the evidence is missing (R-12).
"""
from __future__ import annotations

import json
import re
import sys

from cwa import Snapshot, Tokenizer, assemble
from conftest import ROOT

sys.path.insert(0, str(ROOT / "examples"))
import quickstart  # noqa: E402
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


def test_the_quickstart_sends_the_relevant_chunk_and_traces_the_weak_one():
    result = assemble(quickstart.build_snapshot(quickstart.DOCS))
    request = json.loads(result.payload)
    assert [entry["id"] for entry in request["system"]] == ["policy:tone"]
    [message] = request["messages"]
    assert message["role"] == "user" and "kb:refunds" in message["content"] and "kb:pricing" not in message["content"]
    assert [(row["item_id"], row["reason"]) for row in result.trace["excluded"]] == [("kb:pricing", "below_threshold")]


def test_the_quickstart_refuses_before_any_model_call_without_evidence():
    result = assemble(quickstart.build_snapshot([]))
    assert result.payload is None
    assert result.trace["refused"]["reason"] == "evidence_required"
    assert result.trace["recovery"]["action"] == "request_context"


def test_the_quickstart_maps_the_payload_to_provider_requests():
    request = json.loads(assemble(quickstart.build_snapshot(quickstart.DOCS)).payload)
    anthropic, openai = quickstart.to_anthropic(request), quickstart.to_openai(request)
    assert anthropic["system"] == request["system"][0]["text"] and anthropic["messages"] == request["messages"]
    assert openai["messages"] == [{"role": "system", "content": request["system"][0]["text"]}, *request["messages"]]
    assert "tools" not in anthropic and "tools" not in openai


def test_the_quickstart_runs(capsys):
    quickstart.main()
    out = capsys.readouterr().out
    assert "kb:pricing  below_threshold" in out and "refused: evidence_required" in out


def test_the_readme_shows_what_the_quickstart_prints(capsys):
    quickstart.main()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    shown = re.search(r"uv run python examples/quickstart.py\n```\n\n```text\n(.*?)```", readme, re.S)
    assert shown and shown.group(1) == capsys.readouterr().out
