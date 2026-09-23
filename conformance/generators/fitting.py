"""Builds the budget-fitting and refusal conformance cases from tables of intended outcomes.

Each case lists its candidates, the admission reason for any it excludes, the token_budget cap
actions it intends ("caps"), and the budget-pressure actions it intends ("actions"), each in order:
("omit", id) or ("compress", id, variant_id). Expected traces and
payloads come from those tables, not from a fitting algorithm, so the cases can fail an
implementation. The generator only checks that each table agrees with the budget: the payload
fits after the last action and not before it, and each chosen variant is the one
conformance/README.md's Fitting section selects.
"""
import copy, hashlib, json, os, re, sys

WEB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DEFAULTS = json.load(open(os.path.join(WEB, "contract/slot-defaults.json")))
POLICY = ["token_budget", "variants", "conflict_policy", "lineage", "eligibility", "injection_risk"]
AUTH = {"governance.instructions": "governing", "governance.examples": "governing", "governance.output_contract": "governing",
        "state.user": "state", "state.task": "state", "evidence.knowledge": "reference_only", "evidence.tool_results": "observation",
        "interaction.memory": "generated", "interaction.history": "user", "interaction.query": "user"}
PRODUCER = {"governance.instructions": "policy-registry", "governance.examples": "policy-registry", "governance.output_contract": "policy-registry",
            "state.user": "state-svc", "state.task": "state-svc", "evidence.knowledge": "policy-corpus", "evidence.tool_results": "crm-mcp",
            "interaction.memory": "memory-svc", "interaction.history": "conversation", "interaction.query": "conversation"}
KINDS = {"policy-registry": "policy", "state-svc": "state", "policy-corpus": "retrieval", "crm-mcp": "mcp",
         "memory-svc": "memory", "conversation": "interaction"}
T = "2026-09-22T12:00:00Z"
SCOPE = {"tenant": "acme", "user": "u_91", "session": "s_7", "task": "refund_request"}
WS = re.compile(r"[^\t\n\v\f\r    -     　﻿]+")
count = lambda text: len(WS.findall(text))
esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def item(id, slot, body, **fields):
    d = {"id": id, "slot": slot, "source": "src:" + id, "source_version": "1", "authority": AUTH[slot],
         "trust": "verified" if slot.startswith("governance.") else "unverified", "freshness": "2026-09-22T11:59:00Z", "body": body}
    for f in POLICY:
        d[f] = copy.deepcopy(DEFAULTS[slot][f])
    if slot == "evidence.knowledge":
        d.update(scope={"tenant": "acme"}, freshness="2026-09-12T15:30:00Z")
    if slot == "interaction.memory":
        d.update(source="turn:3", expires="2026-12-01T00:00:00Z")
    d.update(fields)
    return d


def variant(id, body, method="extract"):
    return {"id": id, "body": body, "method": method, "lineage": "extracted"}


PLACEMENT = ["governance.instructions", "governance.examples", "governance.output_contract", "state.user", "state.task",
             "evidence.knowledge", "evidence.tool_results", "interaction.memory", "interaction.history", "interaction.query"]
BASE_SLOTS = {"evidence.knowledge": {"min_relevance": 0.5, "required_scope": ["tenant"]}}


def render(placement, kept):
    """kept: {id: (item, body)}. Returns payload bytes and included rows, per the fixture renderer."""
    parts, included = [], []
    for slot in placement:
        for it, body in sorted((v for v in kept.values() if v[0]["slot"] == slot), key=lambda v: v[0]["id"]):
            b = esc(body)
            parts.append(f'<{slot} id="{esc(it["id"]).replace(chr(34), "&quot;")}">\n{b}\n</{slot}>\n')
            included.append({"slot": slot, "item_id": it["id"], "tokens": count(b), "source_version": it["source_version"]})
    return "".join(parts).encode(), included


def tokens(placement, kept):
    return count(render(placement, kept)[0].decode())


def build(case):
    name, budget, placement = case["id"], case["budget"], case.get("placement", PLACEMENT)
    rows = case["items"]  # (item, admission intent: "admit" or a reason)
    policy = {"route": "support-chat", "version": f"{name}/v1",
              "producers": {p: {"kind": k, "slots": sorted(s for s, q in PRODUCER.items() if q == p)} for p, k in KINDS.items()},
              "slots": copy.deepcopy(BASE_SLOTS)}
    for key, value in case.get("policy", {}).items():
        if key == "slots":
            for slot, rules in value.items():
                policy["slots"].setdefault(slot, {}).update(rules)
        else:
            policy[key] = value
    profile = {"id": "fitting-fixture", "version": 1, "route": "support-chat", "model_family": None, "route_policy_version": policy["version"],
               "placement": [{"slot": s, "wrap": "xml:" + s} for s in placement],
               "evaluation": {"status": "unevaluated", "suite": None, "date": None, "result": None, "artifact": None}}
    batches = {}
    for it, _ in rows:
        batches.setdefault(PRODUCER[it["slot"]], []).append(it)
    snapshot = {"assembly_time": T, "scope": SCOPE, "budget": {"input": budget, "reserved_output": 1024}, "profile": profile,
                "route_policy": policy, "tokenizer": "fixture-whitespace/v1", "renderer": "fixture-xml/v1",
                "batches": [{"producer": {"id": p, "kind": KINDS[p]}, "items": batches[p], "excluded": []} for p in sorted(batches)],
                "conflicts": []}

    admission = sorted(((PRODUCER[it["slot"]], it["id"], r, it["slot"]) for it, r in rows if r != "admit"), key=lambda r: (r[0], r[1]))
    excluded = [{"item_id": i, "reason": r, "stage": "assembler", "slot": s} for _, i, r, s in admission]
    admitted = {it["id"]: it for it, r in rows if r == "admit"}
    kept = {i: (it, it["body"]) for i, it in admitted.items()}
    fits = lambda state: tokens(placement, state) <= budget
    refusal, recovery, actions, caps = case.get("refuse"), case.get("recovery"), case.get("actions", []), case.get("caps", [])
    rank = {"droppable": 0, "compressible": 1, "protected": 2}
    upgrades = policy.get("tier_upgrades", {})
    tier = lambda it: it.get("tier") or max(DEFAULTS[it["slot"]]["tier"], upgrades.get(it["slot"], "droppable"), key=rank.get)
    size = lambda body: count(esc(body))
    over_cap = lambda it: it["token_budget"] is not None and size(it["body"]) > it["token_budget"]
    protected = {i: v for i, v in kept.items() if tier(v[0]) == "protected"}

    if refusal == "protected_content_over_budget":
        assert not fits(protected) or any(over_cap(v[0]) for v in protected.values()), f"{name}: protected items fit"
    compressed = {}
    if refusal not in ("required_slot_missing", "protected_content_over_budget"):
        assert not any(over_cap(v[0]) for v in protected.values()), f"{name}: a protected item exceeds its cap"
        assert {i for i, it in admitted.items() if over_cap(it)} == {a[1] for a in caps}, f"{name}: caps must list exactly the items over their cap"
        for action in caps:
            it = admitted[action[1]]
            within = [v for v in it["variants"] if size(v["body"]) <= it["token_budget"]]
            if action[0] == "omit":
                assert tier(it) == "droppable" or not within, f"{name}: {it['id']} has a variant within its cap"
                del kept[it["id"]]
                excluded.append({"item_id": it["id"], "reason": "over_budget", "stage": "assembler", "slot": it["slot"]})
            else:
                assert tier(it) == "compressible", f"{name}: only compressible items take a variant for their cap"
                chosen = max(within, key=lambda v: (size(v["body"]), -it["variants"].index(v)))
                assert chosen["id"] == action[2], f"{name}: {it['id']} should take {chosen['id']} for its cap"
                kept[it["id"]] = (it, chosen["body"])
                compressed[it["id"]] = chosen
        assert fits(kept) == (not actions), f"{name}: the items {'fit' if fits(kept) else 'do not fit'} before budget pressure"

    for n, action in enumerate(actions):
        it = admitted[action[1]]
        if action[0] == "omit":
            del kept[it["id"]]
            excluded.append({"item_id": it["id"], "reason": "over_budget", "stage": "assembler", "slot": it["slot"]})
            compressed.pop(it["id"], None)
        else:
            current = count(esc(kept[it["id"]][1]))
            shorter = [v for v in it["variants"] if count(esc(v["body"])) < current]
            chosen = next(v for v in shorter if v["id"] == action[2])
            with_variant = lambda v: fits({**kept, it["id"]: (it, v["body"])})
            size = lambda v: count(esc(v["body"]))
            if with_variant(chosen):
                assert not any(with_variant(v) for v in shorter if size(v) > size(chosen)), f"{name}: a longer variant of {it['id']} fits"
            else:
                assert not any(with_variant(v) for v in shorter), f"{name}: a variant of {it['id']} fits, so the shortest is wrong"
                assert chosen == min(shorter, key=size), f"{name}: {chosen['id']} is not the shortest variant"
            kept[it["id"]] = (it, chosen["body"])
            compressed[it["id"]] = chosen
        assert fits(kept) == (n == len(actions) - 1), f"{name}: action {n} {action} leaves the payload {'fitting' if fits(kept) else 'over budget'}"

    payload, included = render(placement, kept)
    trace = {
        "trace_id": name, "profile": {"id": profile["id"], "version": 1}, "budget": snapshot["budget"],
        "result": None if refusal else {"input_tokens": count(payload.decode()), "hash": hashlib.sha256(payload).hexdigest()},
        "included": [] if refusal else included,
        "compressed": [] if refusal else [
            {"slot": row["slot"], "item_id": row["item_id"], "from": count(esc(admitted[row["item_id"]]["body"])), "to": row["tokens"],
             "method": compressed[row["item_id"]]["method"], "variant_id": compressed[row["item_id"]]["id"]}
            for row in included if row["item_id"] in compressed],
        "excluded": excluded, "conflicts": [], "refused": {"bool": bool(refusal), "reason": refusal},
        "context": {"assembly_time": T, "route_policy_version": policy["version"], "tokenizer": "fixture-whitespace/v1", "renderer": "fixture-xml/v1"},
        "defaults_filled": [],
    }
    if recovery:
        trace["recovery"] = {"action": recovery}
    out = os.path.join(WEB, "conformance/cases", name)
    os.makedirs(out, exist_ok=True)
    for file, value in [("snapshot.json", snapshot), ("expected.trace.json", trace),
                        ("case.json", {"id": name, "rules": case["rules"], "description": case["description"]})]:
        open(os.path.join(out, file), "w").write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    payload_file = os.path.join(out, "expected.payload.txt")
    if refusal:
        if os.path.exists(payload_file):
            os.remove(payload_file)
    else:
        open(payload_file, "wb").write(payload)
    print(f"{name}: budget {budget}, {len(admitted)} admitted, {len(actions)} actions -> "
          f"{refusal or trace['result']['input_tokens']}{' / ' + recovery if recovery else ''}")


POLICY_TEXT = "Follow verified refund policy and cite the evidence you use."
QUERY = "Can I refund my Pro plan?"
CONTRACT = "Answer as JSON with fields decision and citations."

CASES = [
    {
        "id": "budget-droppable-order",
        "rules": ["R-16", "R-21", "R-22"],
        "description": "Droppable items shed one at a time by slot priority, then oldest first, and shedding stops as soon as the payload fits; compressible and protected items are untouched.",
        "budget": 44,
        "policy": {"slots": {"governance.examples": {"priority": 1}}},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("ex:1", "governance.examples", "Example: refunds within thirty days are approved.", freshness="2026-09-01T00:00:00Z"), "admit"),
            (item("ex:2", "governance.examples", "Example: annual plans refund pro rata.", freshness="2026-09-10T00:00:00Z"), "admit"),
            (item("user:plan", "state.user", "plan=pro since 2026-09-01", scope={"tenant": "acme", "user": "u_91"}), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within 30 days.", relevance=0.9), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("omit", "user:plan"), ("omit", "ex:1")],
    },
    {
        "id": "budget-variant-choice",
        "rules": ["R-16", "R-18", "R-21"],
        "description": "Once droppable items are gone, compressible items take variants lowest rank first: the longest variant that makes the payload fit, else the shortest; fitting stops before later slots are reached.",
        "budget": 64,
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("ex:1", "governance.examples", "Example: refunds within thirty days are approved."), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within thirty days of purchase when the account is in good standing and no prior refund was issued.",
                  relevance=0.9, variants=[variant("kb:a~mid", "Pro plans refund in full within thirty days of purchase."),
                                           variant("kb:a~short", "Pro: full refund, 30 days.")]), "admit"),
            (item("kb:b", "evidence.knowledge", "Annual plans refund pro rata for unused months, less any discount applied at purchase time.",
                  relevance=0.7, variants=[variant("kb:b~mid", "Annual plans refund pro rata for unused months."),
                                           variant("kb:b~short", "Annual: pro rata.")]), "admit"),
            (item("turn:17", "interaction.history", "I bought the Pro plan on the first of September and it does not fit my team."), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("omit", "ex:1"), ("compress", "kb:b", "kb:b~short"), ("compress", "kb:a", "kb:a~mid")],
    },
    {
        "id": "budget-omit-after-variants",
        "rules": ["R-4", "R-12", "R-16", "R-18", "R-21", "R-22"],
        "description": "With no route order, every compress step runs before any omit step; history sheds oldest first, a compressed item can still be omitted, and a parser route that keeps its evidence minimum is not refused.",
        "budget": 60,
        "policy": {"parser": True, "requires_evidence": True,
                   "slots": {"evidence.knowledge": {"priority": 1, "min_included": 1}, "interaction.history": {"order_by": ["-freshness"]}}},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("contract:json", "governance.output_contract", CONTRACT), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within thirty days of purchase when no prior refund was issued.",
                  relevance=0.9, variants=[variant("kb:a~short", "Pro: full refund within 30 days.")]), "admit"),
            (item("turn:14", "interaction.history", "Hello, I have a question about billing for my team account.", freshness="2026-09-22T11:50:00Z",
                  variants=[variant("turn:14~sum", "User asked about team billing.", "summary")]), "admit"),
            (item("turn:15", "interaction.history", "We upgraded to Pro two weeks ago but the seats are wrong.", freshness="2026-09-22T11:52:00Z"), "admit"),
            (item("turn:16", "interaction.history", "Support said seats cannot be changed mid-cycle.", freshness="2026-09-22T11:54:00Z"), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("compress", "turn:14", "turn:14~sum"), ("compress", "kb:a", "kb:a~short"), ("omit", "turn:14"), ("omit", "turn:15")],
    },
    {
        "id": "budget-route-order",
        "rules": ["R-16", "R-21"],
        "description": "A route fitting_order omits older knowledge before any variant is selected, and a slot the profile places twice counts both occurrences.",
        "budget": 71,
        "placement": ["governance.instructions", "evidence.knowledge", "interaction.history", "governance.instructions", "interaction.query"],
        "policy": {"fitting_order": [{"slot": "evidence.knowledge", "action": "omit"}],
                   "slots": {"evidence.knowledge": {"order_by": ["-freshness"]}}},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("kb:new", "evidence.knowledge", "Since September, Pro plans refund in full within thirty days of purchase.", relevance=0.6,
                  freshness="2026-09-15T00:00:00Z", variants=[variant("kb:new~short", "Pro: full refund, 30 days.")]), "admit"),
            (item("kb:old", "evidence.knowledge", "Until August, Pro plans refunded half the price within fourteen days.", relevance=0.95,
                  freshness="2026-08-01T00:00:00Z", variants=[variant("kb:old~short", "Old: half refund, 14 days.")]), "admit"),
            (item("turn:17", "interaction.history", "I bought the Pro plan on the first of September.",
                  variants=[variant("turn:17~sum", "User bought Pro on 1 September.", "summary")]), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("omit", "kb:old")],
    },
    {
        "id": "budget-route-tiers",
        "rules": ["R-16", "R-18", "R-21"],
        "description": "The route raises state.user to protected and governance.examples to compressible: an item that volunteers droppable sheds first, the examples take variants instead of being dropped, and the user fact is never shed.",
        "budget": 53,
        "policy": {"tier_upgrades": {"state.user": "protected", "governance.examples": "compressible"}},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("ex:1", "governance.examples", "Example: refunds within thirty days are approved.", freshness="2026-09-01T00:00:00Z",
                  variants=[variant("ex:1~short", "Within 30 days: approve.")]), "admit"),
            (item("ex:2", "governance.examples", "Example: annual plans refund pro rata.", freshness="2026-09-10T00:00:00Z",
                  variants=[variant("ex:2~short", "Annual: pro rata.")]), "admit"),
            (item("user:plan", "state.user", "plan=pro since 2026-09-01", scope={"tenant": "acme", "user": "u_91"}), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within 30 days.", relevance=0.9), "admit"),
            (item("kb:faq", "evidence.knowledge", "Older FAQ: refunds may take up to five business days.", relevance=0.6, tier="droppable"), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("omit", "kb:faq"), ("compress", "ex:1", "ex:1~short"), ("compress", "ex:2", "ex:2~short")],
    },
    {
        "id": "budget-token-caps",
        "rules": ["R-3", "R-16", "R-18", "R-21", "R-22"],
        "description": "Items over their token_budget are reduced before shedding: a compressible item takes its longest variant within the cap or is omitted, a droppable item is omitted; budget pressure then takes a still shorter variant, and from counts the original body.",
        "budget": 52,
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("ex:1", "governance.examples", "Example: refunds within thirty days are approved.", token_budget=4), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within thirty days of purchase when no prior refund was issued.",
                  relevance=0.9, token_budget=12, variants=[variant("kb:a~mid", "Pro plans refund in full within thirty days of purchase."),
                                                           variant("kb:a~short", "Pro: full refund, 30 days.")]), "admit"),
            (item("kb:b", "evidence.knowledge", "Annual plans refund pro rata for unused months, less any discount.", relevance=0.7,
                  token_budget=6, variants=[variant("kb:b~mid", "Annual plans refund pro rata for unused months.")]), "admit"),
            (item("turn:17", "interaction.history", "I bought the Pro plan on the first of September and it does not fit my team.",
                  variants=[variant("turn:17~sum", "User bought Pro on 1 September.", "summary")]), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "caps": [("omit", "kb:b"), ("compress", "kb:a", "kb:a~mid"), ("omit", "ex:1")],
        "actions": [("compress", "kb:a", "kb:a~short")],
    },
    {
        "id": "protected-over-cap",
        "rules": ["R-16", "R-17", "R-21"],
        "description": "A protected item whose body exceeds its own token_budget refuses the assembly, although the payload fits budget.input; nothing is truncated or shed, and the knowledge item over its own cap gets no row.",
        "budget": 4096,
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT, token_budget=5), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within 30 days.", relevance=0.9, token_budget=4), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "refuse": "protected_content_over_budget",
    },
    {
        "id": "required-slot-missing",
        "rules": ["R-4", "R-17", "R-21", "R-22"],
        "description": "On a parser route whose only output contract fails admission, assembly refuses before fitting: no payload, result null, included empty, admission rows kept.",
        "budget": 4096,
        "policy": {"parser": True},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("contract:json", "governance.output_contract", CONTRACT, trust="unverified"), "untrusted_in_governance"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within 30 days.", relevance=0.9), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "refuse": "required_slot_missing",
    },
    {
        "id": "protected-over-budget",
        "rules": ["R-16", "R-17", "R-21"],
        "description": "When protected items alone exceed budget.input, assembly refuses without shedding anything: no payload and no over_budget rows.",
        "budget": 25,
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("task:8821", "state.task", "refund_request: verify_eligibility=done, collect_reason=pending, issue_refund=pending"), "admit"),
            (item("ex:1", "governance.examples", "Example: refunds within thirty days are approved."), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within 30 days.", relevance=0.9), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "refuse": "protected_content_over_budget",
    },
    {
        "id": "evidence-request-context",
        "rules": ["R-12", "R-17", "R-21", "R-22"],
        "description": "A route that requires evidence refuses with recovery request_context when admission leaves no evidence, although everything else fits.",
        "budget": 4096,
        "policy": {"requires_evidence": True},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("kb:low", "evidence.knowledge", "Gift cards are not refundable.", relevance=0.2), "below_threshold"),
            (item("kb:other", "evidence.knowledge", "Globex refunds in 60 days.", relevance=0.9, scope={"tenant": "globex"}), "out_of_scope"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "refuse": "evidence_required", "recovery": "request_context",
    },
    {
        "id": "evidence-precompute-summary",
        "rules": ["R-12", "R-16", "R-17", "R-21", "R-22"],
        "description": "Fitting leaves fewer knowledge items than the route's min_included, and an omitted item had no variants, so the refusal recommends precompute_summary and keeps the fitting rows.",
        "budget": 40,
        "policy": {"requires_evidence": True, "slots": {"evidence.knowledge": {"min_included": 2}}},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within thirty days of purchase for new customers.", relevance=0.9,
                  variants=[variant("kb:a~short", "Pro: full refund, 30 days.")]), "admit"),
            (item("kb:b", "evidence.knowledge", "Refunds are issued to the original payment method within ten business days.", relevance=0.8), "admit"),
            (item("kb:c", "evidence.knowledge", "Annual plans refund pro rata for unused months after the first thirty days.", relevance=0.7,
                  variants=[variant("kb:c~short", "Annual: pro rata.")]), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("compress", "kb:c", "kb:c~short"), ("compress", "kb:a", "kb:a~short"), ("omit", "kb:c"), ("omit", "kb:b")],
        "refuse": "evidence_required", "recovery": "precompute_summary",
    },
    {
        "id": "evidence-retrieve-narrower",
        "rules": ["R-12", "R-16", "R-17", "R-21", "R-22"],
        "description": "Every evidence item had variants and none fit beside the protected items, so fitting omits all evidence and the refusal recommends retrieve_narrower.",
        "budget": 25,
        "policy": {"requires_evidence": True},
        "items": [
            (item("policy:v12", "governance.instructions", POLICY_TEXT), "admit"),
            (item("kb:a", "evidence.knowledge", "Pro plans refund in full within thirty days of purchase.", relevance=0.9,
                  variants=[variant("kb:a~short", "Pro: full refund within thirty days.")]), "admit"),
            (item("obs:order-42", "evidence.tool_results", "order 42: pro plan, purchased 2026-09-01, paid by card ending 4242",
                  variants=[variant("obs:order-42~short", "order 42: pro, 2026-09-01")]), "admit"),
            (item("turn:18", "interaction.query", QUERY), "admit"),
        ],
        "actions": [("compress", "kb:a", "kb:a~short"), ("compress", "obs:order-42", "obs:order-42~short"),
                    ("omit", "kb:a"), ("omit", "obs:order-42")],
        "refuse": "evidence_required", "recovery": "retrieve_narrower",
    },
]

if __name__ == "__main__":
    for case in CASES:
        build(case)
