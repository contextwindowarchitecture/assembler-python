"""An exact tokenizer for OpenAI models: an example of a caller's tokenizer, kept outside the pure core.

tiktoken fetches an encoding over the network the first time it is used, so build the adapter before
freezing a snapshot. assemble() reads nothing outside the snapshot (R-23), and the adapter only counts.

    import tiktoken
    from tiktoken_tokenizer import TiktokenTokenizer

    tokenizer = TiktokenTokenizer(tiktoken.get_encoding("o200k_base"))   # loads the encoding now
    snapshot = Snapshot.from_json(document, tokenizers={tokenizer.id: tokenizer})
    # document["tokenizer"] == "tiktoken-o200k_base/v1"; the counts are exact, so no margin is needed

Version the id when the encoding or this counting changes, because the id is what a stored snapshot
replays with.
"""
from __future__ import annotations

from typing import Any


class TiktokenTokenizer:
    def __init__(self, encoding: Any, id: str | None = None) -> None:
        self._encoding = encoding
        self.id = id or f"tiktoken-{encoding.name}/v1"

    def count(self, text: str) -> int:
        # Bodies are untrusted, and one may spell a special token such as <|endoftext|>. tiktoken refuses
        # that text by default; count it as the ordinary text it is.
        return len(self._encoding.encode(text, disallowed_special=()))
