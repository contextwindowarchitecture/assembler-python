"""Quickstart: assemble one support-chat request, then watch the assembler refuse one.

    uv run python examples/quickstart.py

A snapshot is everything assembly may look at, frozen: the items producers proposed, the route's policy, the
placement profile, the budget, the tokenizer, the renderer and the clock. assemble() turns it into a payload and a
trace, or a refusal and a trace, and reads nothing else (R-23). The README's Quickstart mirrors this file.
"""
from __future__ import annotations

import json
from typing import Any

from cwa import Snapshot, assemble

NOW = "2026-10-21T12:00:00Z"

# What a retriever returned for the question, with its scores. The route below admits only chunks scoring 0.5 or more.
DOCS = [
    {"id": "kb:refunds", "body": "Pro plans can be refunded in full within 30 days of purchase.", "relevance": 0.82},
    {"id": "kb:pricing", "body": "The Pro plan costs $20 a month, billed annually.", "relevance": 0.31},
]

# Which producers may write which slots, and the rules for each slot. Versioned, so a trace names the policy it used.
ROUTE_POLICY = {
    "route": "support-chat",
    "version": "support-chat/v1",
    "producers": {
        "policy-registry": {"kind": "policy", "slots": ["governance.instructions"]},
        "docs-search": {"kind": "retrieval", "slots": ["evidence.knowledge"]},
        "conversation": {"kind": "interaction", "slots": ["interaction.query"]},
    },
    "slots": {"evidence.knowledge": {"min_relevance": 0.5}},
    "requires_evidence": True,  # refuse rather than let the model answer from nothing (R-12)
}

# Where each slot lands in the request. Instructions go to the system channel; the rest is escaped material in the
# user message, so a retrieved chunk can never speak as the system (R-7, R-10).
PROFILE = {
    "spec": "cwa/draft",
    "id": "support-chat-default",
    "version": 1,
    "route": "support-chat",
    "model_family": None,
    "route_policy_version": "support-chat/v1",
    "placement": [
        {"slot": "governance.instructions", "wrap": "system"},
        {"slot": "evidence.knowledge", "wrap": "xml:evidence"},
        {"slot": "interaction.query", "wrap": "xml:query"},
    ],
    "evaluation": {"status": "unevaluated", "suite": None, "date": None, "result": None, "artifact": None},
}


def item(id: str, slot: str, authority: str, trust: str, body: str, **extra: Any) -> dict[str, Any]:
    """An item with the eight fields every item carries; the slot's defaults fill in the rest (R-2, R-3)."""
    return {"id": id, "slot": slot, "source": f"src:{id}", "source_version": "1", "authority": authority,
            "trust": trust, "freshness": NOW, "body": body, **extra}


def build_snapshot(docs: list[dict[str, Any]]) -> Snapshot:
    """Freeze one request. Everything that can change the payload is in here; nothing is read later."""
    batches = [
        {"producer": {"id": "policy-registry", "kind": "policy"}, "excluded": [], "items": [
            item("policy:tone", "governance.instructions", "governing", "verified",
                 "Answer from the evidence only, and say so when it does not cover the question."),
        ]},
        {"producer": {"id": "docs-search", "kind": "retrieval"}, "excluded": [], "items": [
            item(d["id"], "evidence.knowledge", "reference_only", "unverified", d["body"], relevance=d["relevance"])
            for d in docs
        ]},
        {"producer": {"id": "conversation", "kind": "interaction"}, "excluded": [], "items": [
            item("turn:1", "interaction.query", "user", "unverified", "Can I get a refund on my Pro plan?"),
        ]},
    ]
    return Snapshot.freeze(
        assembly_time=NOW,
        scope={"tenant": "acme", "user": "u_42", "session": "s_1", "task": "support"},
        budget={"input": 8000, "reserved_output": 1024, "margin_percent": 10},  # headroom for an estimating tokenizer
        profile=PROFILE,
        route_policy=ROUTE_POLICY,
        tokenizer="estimate-utf8/v1",  # pass your model's own tokenizer for exact counts (see Extending)
        renderer="cwa-messages/v1",    # {system, tools, messages}, ready to map onto a provider's request
        batches=batches,
        conflicts=[],
    )


def to_anthropic(request: dict[str, Any]) -> dict[str, Any]:
    """Keyword arguments for anthropic.Anthropic().messages.create, less model and max_tokens."""
    out: dict[str, Any] = {"system": "\n\n".join(e["text"] for e in request["system"]), "messages": request["messages"]}
    if request["tools"]:
        # A tool's text is the body its capability producer wrote, in the provider's tool format.
        out["tools"] = [json.loads(t["text"]) for t in request["tools"]]
    return out


def to_openai(request: dict[str, Any]) -> dict[str, Any]:
    """Keyword arguments for openai.OpenAI().chat.completions.create, less model."""
    system = [{"role": "system", "content": e["text"]} for e in request["system"]]
    out: dict[str, Any] = {"messages": [*system, *request["messages"]]}
    if request["tools"]:
        out["tools"] = [json.loads(t["text"]) for t in request["tools"]]
    return out


def main() -> None:
    result = assemble(build_snapshot(DOCS))
    request = json.loads(result.payload)
    print(json.dumps(to_anthropic(request), indent=2))
    print(f"\n{result.trace['result']['input_tokens']} tokens; left out:")
    for row in result.trace["excluded"]:
        print(f"  {row['item_id']}  {row['reason']}")

    # The retriever found nothing: no payload, so no model call, and the trace says what to do next.
    refused = assemble(build_snapshot([]))
    print(f"\nrefused: {refused.trace['refused']['reason']}, recovery: {refused.trace['recovery']['action']}")


if __name__ == "__main__":
    main()
