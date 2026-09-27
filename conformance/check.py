#!/usr/bin/env python3
"""Checks the CWA contract's own consistency, and regenerates the copies derived from it.

    python3 conformance/check.py          # verify; exit 1 on any contract problem
    python3 conformance/check.py --write  # also rewrite SPEC.md and the spec page's RULES block from contract/requirements.json

It checks, in this order:

- every conformance case: snapshot and expected trace valid against the schemas, `context.snapshot_digest` equal to the
  digest conformance/README.md defines, `result.hash` equal to the SHA-256 of expected.payload.txt, the refusal shape R-17
  requires, and the profile, route policy version, spec and margin repeated from the snapshot;
- every rejection: its snapshot breaks exactly one of the Snapshot checks in conformance/README.md, and every case passes them all;
- the registry: profiles and route policies valid, and lock.json pinning each with the digest the README defines;
- contract/reasons.json against the schemas that list its codes and against the requirements that cite them: each code is
  named by the rule it is attributed to, so R-21's "the conditions those codes name" always has a home;
- every requirement exercised by at least one case, except those listed in UNTESTABLE;
- SPEC.md and the spec page's RULES block equal to what contract/requirements.json generates.

The two assembler reports under contract/ are checked for schema validity and coverage of the cases now on disk, and any
problem there is a warning, since the reports are artifacts of another repository.

Needs the jsonschema package (with referencing). Run from anywhere; paths resolve from this file.
"""
import argparse, glob, hashlib, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(HERE, "generators"))
from digest import jcs, snapshot_digest  # noqa: E402

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover
    sys.exit("check.py needs the jsonschema package: pip install jsonschema")

UNTESTABLE = {"R-5"}  # the application enforces invariants; nothing observable in assembly can prove it
XML_WRAP = re.compile(r"^xml:[A-Za-z_][A-Za-z0-9_.-]*$")
POLICY_FIELDS = ["token_budget", "variants", "conflict_policy", "lineage", "eligibility", "injection_risk"]

problems, warnings = [], []
def problem(msg): problems.append(msg)
def warn(msg): warnings.append(msg)
def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)
def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------------------------- schemas
schemas = {}
for f in glob.glob(os.path.join(ROOT, "schema", "*.json")):
    s = json.load(open(f, encoding="utf-8"))
    schemas[s["$id"]] = s
registry = Registry().with_resources([(k, Resource.from_contents(v)) for k, v in schemas.items()])
def validator(name):
    return Draft202012Validator(schemas[f"https://contextwindowarchitecture.io/schema/{name}"], registry=registry, format_checker=FormatChecker())
V_SNAPSHOT, V_TRACE, V_PROFILE, V_POLICY = validator("snapshot.schema.json"), validator("trace.schema.json"), validator("profile.schema.json"), validator("route_policy.schema.json")
V_LOCK, V_REPORT = validator("registry_lock.schema.json"), validator("conformance_report.schema.json")
def first_error(v, doc):
    errors = list(v.iter_errors(doc))
    return None if not errors else f"{errors[0].message[:160]} at /{'/'.join(str(p) for p in errors[0].absolute_path)}"


# ---------------------------------------------------------------------------------------------- snapshot checks (conformance/README.md)
def well_formed(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return True
        except UnicodeEncodeError:
            return False
    if isinstance(value, list):
        return all(well_formed(v) for v in value)
    if isinstance(value, dict):
        return all(well_formed(k) and well_formed(v) for k, v in value.items())
    return True

def realizable(renderer, placement):
    if renderer == "fixture-xml/v1":
        return all(XML_WRAP.match(e["wrap"]) for e in placement)
    if renderer == "cwa-messages/v1":
        seen_xml = False
        for e in placement:
            wrap, slot = e["wrap"], e["slot"]
            if wrap not in ("system", "tools") and not XML_WRAP.match(wrap): return False
            if wrap == "system" and not slot.startswith("governance."): return False
            if wrap == "tools" and slot != "governance.capabilities": return False
            if wrap == "system" and seen_xml: return False
            seen_xml = seen_xml or wrap.startswith("xml:")
        return True
    return None  # unknown renderer: the case is skipped, not judged

def snapshot_checks(snap):
    """The names of the Snapshot checks the snapshot breaks. The schema counts as one check."""
    broken = []
    if first_error(V_SNAPSHOT, snap): broken.append("schema")
    if not well_formed(snap): broken.append("i-json")
    producers = [b["producer"]["id"] for b in snap.get("batches", []) if isinstance(b, dict) and "producer" in b]
    if len(producers) != len(set(producers)): broken.append("one-batch-per-producer")
    ids = set()
    for b in snap.get("batches", []):
        for it in b.get("items", []):
            if isinstance(it, dict) and isinstance(it.get("id"), str): ids.add(it["id"])
        for row in b.get("excluded", []): ids.add(row.get("item_id"))
    groups = snap.get("conflicts", [])
    gids = [g.get("id") for g in groups]
    seen, flags = set(), set()
    if len(gids) != len(set(gids)): flags.add("conflict-group-ids")
    facts = snap.get("route_policy", {}).get("facts", {})
    for g in groups:
        for i in g.get("items", []):
            if i not in ids: flags.add("conflict-unknown-item")
            if i in seen: flags.add("conflict-overlap")
            seen.add(i)
        if g.get("kind") == "fact" and g.get("fact") not in facts: flags.add("conflict-unknown-fact")
    broken += sorted(flags)
    for b in snap.get("batches", []):
        candidates = {it.get("id") for it in b.get("items", []) if isinstance(it, dict)}
        for row in b.get("excluded", []):
            for field in ("duplicate_of", "superseded_by"):
                if field in row and row[field] not in candidates: broken.append(f"producer-exclusion-{field}")
    profile, policy = snap.get("profile", {}), snap.get("route_policy", {})
    if profile.get("route") != policy.get("route"): broken.append("profile-route")
    if profile.get("route_policy_version") != policy.get("version"): broken.append("profile-route-policy-version")
    placed = {e.get("slot") for e in profile.get("placement", [])}
    if "governance.instructions" not in placed: broken.append("profile-instructions")
    if "interaction.query" not in placed: broken.append("profile-query")
    if policy.get("parser") and "governance.output_contract" not in placed: broken.append("profile-output-contract")
    if realizable(snap.get("renderer"), profile.get("placement", [])) is False: broken.append("unrealizable")
    return broken


# ---------------------------------------------------------------------------------------------- cases
case_dirs = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "*", "")))
rejection_dirs = sorted(glob.glob(os.path.join(ROOT, "conformance", "rejections", "*", "")))
requirements = load("contract/requirements.json")
rule_ids = [r["id"] for r in requirements]
covered = {}

for d in case_dirs:
    cid = os.path.basename(d.rstrip("/"))
    for name in ("case.json", "snapshot.json", "expected.trace.json"):
        if not os.path.exists(d + name): problem(f"{cid}: {name} missing")
    case, snap, trace = json.load(open(d + "case.json")), json.load(open(d + "snapshot.json")), json.load(open(d + "expected.trace.json"))
    if case.get("id") != cid: problem(f"{cid}: case.json id is {case.get('id')!r}")
    for r in case.get("rules", []):
        if r not in rule_ids: problem(f"{cid}: names unknown requirement {r}")
        covered.setdefault(r, []).append(cid)
    if (e := first_error(V_SNAPSHOT, snap)): problem(f"{cid}: snapshot invalid: {e}")
    if (b := snapshot_checks(snap)): problem(f"{cid}: snapshot breaks {b}")
    if (e := first_error(V_TRACE, trace)): problem(f"{cid}: trace invalid: {e}")
    if trace["context"]["snapshot_digest"] != snapshot_digest(snap): problem(f"{cid}: snapshot_digest does not match the normalized snapshot")
    if trace["context"]["spec"] != snap["profile"]["spec"]: problem(f"{cid}: context.spec differs from the profile's spec")
    if trace["context"]["route_policy_version"] != snap["route_policy"]["version"]: problem(f"{cid}: route_policy_version differs from the snapshot's")
    if (trace["profile"]["id"], trace["profile"]["version"]) != (snap["profile"]["id"], snap["profile"]["version"]): problem(f"{cid}: profile id/version differ from the snapshot's")
    if trace["budget"].get("margin_percent") != snap["budget"].get("margin_percent"): problem(f"{cid}: budget.margin_percent not repeated as the snapshot sets it")
    payload = d + "expected.payload.txt"
    if trace["result"] is None:
        if os.path.exists(payload): problem(f"{cid}: refusal has an expected.payload.txt")
        if not trace["refused"]["bool"] or not trace["refused"]["reason"] or trace["included"] or trace["compressed"]: problem(f"{cid}: refused trace shape (R-17)")
    else:
        if not os.path.exists(payload): problem(f"{cid}: expected.payload.txt missing")
        elif hashlib.sha256(open(payload, "rb").read()).hexdigest() != trace["result"]["hash"]: problem(f"{cid}: result.hash is not the SHA-256 of expected.payload.txt")
        if trace["refused"]["bool"] or trace["refused"]["reason"] is not None: problem(f"{cid}: successful trace shape (R-17)")
    # defaults_filled: one row per item and field in R-3 order, ordered by item_id (README, Array order)
    rows = [(r["item_id"], r["field"]) for r in trace["defaults_filled"]]
    if rows != sorted(rows, key=lambda r: (r[0].encode("utf-16-be"), POLICY_FIELDS.index(r[1]) if r[1] in POLICY_FIELDS else 99)): problem(f"{cid}: defaults_filled not in README order")
    if any(f not in POLICY_FIELDS for _, f in rows): problem(f"{cid}: defaults_filled names a field outside R-3")

for d in rejection_dirs:
    cid = os.path.basename(d.rstrip("/"))
    case = json.load(open(d + "case.json"))
    if case.get("id") != cid: problem(f"{cid}: case.json id is {case.get('id')!r}")
    for r in case.get("rules", []):
        if r not in rule_ids: problem(f"{cid}: names unknown requirement {r}")
        covered.setdefault(r, []).append(cid)
    if os.path.exists(d + "expected.trace.json") or os.path.exists(d + "expected.payload.txt"): problem(f"{cid}: a rejection has no expected trace or payload")
    try:
        snap = json.load(open(d + "snapshot.json", encoding="utf-8"))
    except ValueError as ex:
        problem(f"{cid}: snapshot.json does not parse: {ex}")
        continue
    b = snapshot_checks(snap)
    if len(b) != 1: problem(f"{cid}: a rejection breaks exactly one Snapshot check, this one breaks {b or 'none'}")

for r in rule_ids:
    if r not in covered and r not in UNTESTABLE: problem(f"{r}: no case or rejection exercises it")


# ---------------------------------------------------------------------------------------------- registry
profiles, policies, lock = load("conformance/registry/profiles.json"), load("conformance/registry/route-policies.json"), load("conformance/registry/lock.json")
if (e := first_error(V_LOCK, lock)): problem(f"registry lock invalid: {e}")
seen_ids = set()
for p in profiles:
    if (e := first_error(V_PROFILE, p)): problem(f"profile {p.get('id')}: invalid: {e}")
    digest = hashlib.sha256(jcs({k: v for k, v in p.items() if k != "evaluation"}).encode()).hexdigest()
    entry = next((l for l in lock["profiles"] if l["id"] == p["id"] and l["version"] == p["version"]), None)
    if entry is None: problem(f"profile {p['id']}/{p['version']}: not pinned in lock.json")
    elif entry["sha256"] != digest: problem(f"profile {p['id']}/{p['version']}: lock digest differs from its content")
for r in policies:
    if (e := first_error(V_POLICY, r)): problem(f"route policy {r.get('route')}/{r.get('version')}: invalid: {e}")
    digest = hashlib.sha256(jcs(r).encode()).hexdigest()
    entry = next((l for l in lock["route_policies"] if l["route"] == r["route"] and l["version"] == r["version"]), None)
    if entry is None: problem(f"route policy {r['route']}/{r['version']}: not pinned in lock.json")
    elif entry["sha256"] != digest: problem(f"route policy {r['route']}/{r['version']}: lock digest differs from its content")
for kind, key in (("profiles", lambda l: (l["id"], l["version"])), ("route_policies", lambda l: (l["route"], l["version"]))):
    keys = [key(l) for l in lock[kind]]
    if len(keys) != len(set(keys)): problem(f"lock.json lists a {kind[:-1]} identity twice")
have = {(r["route"], r["version"]) for r in policies}
for p in profiles:
    if (p["route"], p["route_policy_version"]) not in have: warn(f"profile {p['id']} names route policy {p['route']}/{p['route_policy_version']}, which the registry does not hold, so no valid snapshot can carry it")


# ---------------------------------------------------------------------------------------------- reasons and requirements
reasons = load("contract/reasons.json")
codes = [r["code"] for r in reasons]
if len(codes) != len(set(codes)): problem("contract/reasons.json repeats a code")
exclusions = [r["code"] for r in reasons if r["kind"] == "exclusion" and not r["code"].startswith("missing_field")]
batch_enum = schemas["https://contextwindowarchitecture.io/schema/producer_batch.schema.json"]["properties"]["excluded"]["items"]["properties"]["reason"]["anyOf"][0]["enum"]
if batch_enum != exclusions: problem("producer_batch.schema.json's reason enum differs from contract/reasons.json's exclusion codes, in content or order")
texts = {r["id"]: r["text"] for r in requirements}
for r in reasons:
    base = r["code"].split(":")[0]
    if r["rule"] not in texts: problem(f"reason {r['code']}: attributed to unknown rule {r['rule']}")
    elif not re.search(r"\b" + re.escape(base) + r"\b", texts[r["rule"]]): problem(f"reason {r['code']}: attributed to {r['rule']}, whose text never names it")
named = {m for t in texts.values() for m in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", t)}
for name in sorted(named):
    if name in {c.split(":")[0] for c in codes}: continue
for r in requirements:
    for ref in re.findall(r"\bR-(\d+)\b", r["text"]):
        if f"R-{ref}" not in texts: problem(f"{r['id']}: cites R-{ref}, which does not exist")
    if r["keyword"] not in ("MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY"): problem(f"{r['id']}: keyword {r['keyword']!r}")
if rule_ids != [f"R-{i}" for i in range(1, len(rule_ids) + 1)]: problem("requirements are not numbered R-1..R-n in order")
slot_defaults = load("contract/slot-defaults.json")
item_slots = schemas["https://contextwindowarchitecture.io/schema/context_item.schema.json"]["properties"]["slot"]["enum"]
if list(slot_defaults) != item_slots: problem("contract/slot-defaults.json's slots differ from context_item.schema.json's slot enum, in content or order")
for slot, d in slot_defaults.items():
    if set(POLICY_FIELDS) - set(d): problem(f"slot default {slot}: missing a policy field")


# ---------------------------------------------------------------------------------------------- derived copies
def render_spec_md():
    out = ["# CWA draft — numbered requirements", "",
           "Generated from `contract/requirements.json`. The [Spec page](./spec.html) provides the normative definitions and context. Published schemas in `schema/` define JSON field shapes.", ""]
    for r in requirements:
        out += [f"## {r['id']}: {r['summary']}", "", r["text"], ""]
    return "\n".join(out)

def render_rules_block():
    rules = [[r["section"], r["keyword"], r["summary"], r["text"]] for r in requirements]
    return "const RULES = " + json.dumps(rules, indent=2, ensure_ascii=False) + ";"

RULES_RE = re.compile(r"const RULES = \[[\s\S]*?\n\];")
def check_or_write(write):
    spec_md, html = read("SPEC.md"), read("spec.html")
    want_md, want_rules = render_spec_md(), render_rules_block()
    m = RULES_RE.search(html)
    if not m: problem("spec.html: RULES block not found"); return
    if write:
        if spec_md != want_md:
            open(os.path.join(ROOT, "SPEC.md"), "w", encoding="utf-8").write(want_md); print("wrote SPEC.md")
        if m.group(0) != want_rules:
            open(os.path.join(ROOT, "spec.html"), "w", encoding="utf-8").write(html[:m.start()] + want_rules + html[m.end():]); print("wrote spec.html RULES block")
    else:
        if spec_md != want_md: problem("SPEC.md differs from contract/requirements.json; run check.py --write")
        if m.group(0) != want_rules: problem("spec.html's RULES block differs from contract/requirements.json; run check.py --write")
    if not re.search(r"Specification · draft · \d{4}-\d{2}-\d{2}", html): problem("spec.html: draft date header not found")


# ---------------------------------------------------------------------------------------------- assembler reports (warnings)
disk_cases = {os.path.basename(d.rstrip("/")) for d in case_dirs}
disk_rejections = {os.path.basename(d.rstrip("/")) for d in rejection_dirs}
for path in sorted(glob.glob(os.path.join(ROOT, "contract", "assembler*-conformance.json"))):
    rel = os.path.relpath(path, ROOT)
    report = json.load(open(path, encoding="utf-8"))
    if (e := first_error(V_REPORT, report)): warn(f"{rel}: not valid against conformance_report.schema.json: {e}")
    ran = {c["id"] for c in report.get("cases", [])}
    ran_rej = {c["id"] for c in report.get("rejections", [])}
    if disk_cases - ran: warn(f"{rel}: cases not in the report: {sorted(disk_cases - ran)}")
    if disk_rejections - ran_rej: warn(f"{rel}: rejections not in the report: {sorted(disk_rejections - ran_rej)}")
    failed = [c["id"] for c in report.get("cases", []) if c.get("outcome") != "passed"] + [c["id"] for c in report.get("rejections", []) if c.get("outcome") != "rejected"]
    if failed: warn(f"{rel}: not passing: {failed}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite SPEC.md and the spec page's RULES block from contract/requirements.json")
    args = ap.parse_args()
    check_or_write(args.write)
    print(f"{len(case_dirs)} cases, {len(rejection_dirs)} rejections, {len(requirements)} requirements, {len(reasons)} reason codes")
    for w in warnings: print("warning:", w)
    for p in problems: print("PROBLEM:", p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)

if __name__ == "__main__":
    main()
