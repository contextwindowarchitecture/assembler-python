from __future__ import annotations


class EstimateUtf8:
    """UTF-8 bytes divided by 4, rounded up: a portable estimate for models with no local tokenizer.

    Low for scripts of several bytes a character that take about one token each, such as Chinese and
    Japanese, so pair it with a budget.margin_percent that covers the route's text (R-16).
    """

    id = "estimate-utf8/v1"

    def count(self, text: str) -> int:
        return (len(text.encode("utf-8")) + 3) // 4
