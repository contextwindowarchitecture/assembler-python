"""Builds conformance/rejections/: snapshots that break exactly one of conformance/README.md's Snapshot checks
or their schemas. A conformant assembler rejects each before assembly, with no payload and no trace (R-17).

Each case changes fixture-three-slot's snapshot in one place. The website's tests check each with
contract.js's checkSnapshot, which must find exactly one problem, independently of this generator.
"""
import copy, json, os, shutil, sys

WEB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
BASE = json.load(open(os.path.join(WEB, "conformance/cases/fixture-three-slot/snapshot.json")))
LONE = "LONE"  # stands in for an unpaired surrogate, which UTF-8 cannot encode; written as the escape \ud800


def group(id, items, **extra):
    return {"id": id, "kind": "instruction", "items": items, **extra}


def set_conflicts(*groups):
    return lambda s: s.update(conflicts=list(groups))


def batch(producer):
    return lambda s: next(b for b in s["batches"] if b["producer"]["id"] == producer)


CASES = [
    ("schema-missing-budget", ["R-17"], "The snapshot has no budget, which its schema requires.",
     lambda s: s.pop("budget")),
    ("schema-profile-spec", ["R-17", "R-19"], "The profile was written for another specification: its spec is cwa/1, and the profile schema fixes cwa/draft.",
     lambda s: s["profile"].update(spec="cwa/1")),
    ("unpaired-surrogate", ["R-17", "R-23"], "An item body ends in an unpaired surrogate, so the snapshot is not well-formed Unicode and has no digest.",
     lambda s: batch("policy-registry")(s)["items"][0].update(body=batch("policy-registry")(s)["items"][0]["body"] + LONE)),
    ("producer-in-two-batches", ["R-15", "R-17"], "Two batches name the same producer, policy-registry; a batch is one authenticated producer's output for the call.",
     lambda s: batch("conversation")(s).update(producer=copy.deepcopy(batch("policy-registry")(s)["producer"]))),
    ("conflict-group-unknown-item", ["R-11", "R-17"], "A conflict group names an item id that is neither a candidate nor a producer exclusion in the snapshot.",
     set_conflicts(group("g1", ["policy:v12", "nope"]))),
    ("conflict-group-repeated-id", ["R-11", "R-17"], "Two conflict groups share the id g1.",
     set_conflicts(group("g1", ["policy:v12", "turn:18"]), group("g1", ["refunds-eu:v17#p4", "memory:expired"]))),
    ("conflict-group-overlap", ["R-11", "R-17"], "turn:18 belongs to two conflict groups; an item belongs to at most one.",
     set_conflicts(group("g1", ["policy:v12", "turn:18"]), group("g2", ["turn:18", "refunds-eu:v17#p4"]))),
    ("conflict-group-unknown-fact", ["R-11", "R-17"], "A fact group names refund_window, which the route policy's facts do not define.",
     set_conflicts(group("g1", ["policy:v12", "refunds-eu:v17#p4"], kind="fact", fact="refund_window"))),
    ("duplicate-of-unknown", ["R-13", "R-17"], "A producer exclusion's duplicate_of names an item that is not a candidate in its batch.",
     lambda s: batch("memory-svc")(s)["excluded"].append(
         {"item_id": "memory:dup", "reason": "duplicate_content", "stage": "producer", "duplicate_of": "memory:gone"})),
    ("profile-route-mismatch", ["R-17", "R-20"], "The profile is for route another-route, and the route policy for contract-fixture.",
     lambda s: s["profile"].update(route="another-route")),
    ("profile-route-policy-mismatch", ["R-17", "R-20"], "The profile expects route policy fixture/v2, and the snapshot carries fixture/v1.",
     lambda s: s["profile"].update(route_policy_version="fixture/v2")),
    ("profile-missing-query", ["R-4", "R-17", "R-20"], "The profile does not place interaction.query, which every assembly needs.",
     lambda s: s["profile"].update(placement=[p for p in s["profile"]["placement"] if p["slot"] != "interaction.query"])),
    ("profile-missing-output-contract", ["R-4", "R-17", "R-20"], "The route sets parser: true, and the profile does not place governance.output_contract.",
     lambda s: s["route_policy"].update(parser=True)),
    ("profile-unrealizable", ["R-7", "R-17", "R-20"], "The profile wraps evidence.knowledge as system, which fixture-xml/v1 cannot render.",
     lambda s: s["profile"]["placement"][1].update(wrap="system")),
]

if __name__ == "__main__":
    root = os.path.join(WEB, "conformance/rejections")
    shutil.rmtree(root, ignore_errors=True)
    for name, rules, description, mutate in CASES:
        snapshot = copy.deepcopy(BASE)
        mutate(snapshot)
        out = os.path.join(root, name)
        os.makedirs(out)
        text = json.dumps(snapshot, indent=2, ensure_ascii=False).replace(LONE, "\\ud800") + "\n"
        open(os.path.join(out, "snapshot.json"), "w", encoding="utf-8").write(text)
        open(os.path.join(out, "case.json"), "w", encoding="utf-8").write(
            json.dumps({"id": name, "rules": rules, "description": description}, indent=2, ensure_ascii=False) + "\n")
    print(f"rejections: {len(CASES)} cases")
