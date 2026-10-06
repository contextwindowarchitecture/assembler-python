#!/usr/bin/env python3
"""Checks the CWA contract's own consistency, and regenerates the copies derived from it.

    python3 conformance/check.py          # verify; exit 1 on any contract problem
    python3 conformance/check.py --write  # also rewrite the generated blocks in SPEC.md and guides/, and SPEC.md's date

It checks, in this order:

- every conformance case: snapshot and expected trace valid against the schemas, `context.snapshot_digest` equal to the
  digest conformance/README.md defines, `result.hash` equal to the SHA-256 of expected.payload.txt, the refusal shape R-17
  requires, and the profile, route policy version, spec and margin repeated from the snapshot;
- every rejection: its snapshot breaks exactly one of the Snapshot checks in conformance/README.md, and every case passes them all;
- the registry: profiles and route policies valid, and lock.json pinning each with the digest the README defines;
- contract/reasons.json against the schemas that list its codes and against the requirements that cite them: each code is
  named by the rule it is attributed to, so R-21's "the conditions those codes name" always has a home;
- contract/model.json, the lists the Spec page shows: its slots the same set as contract/slot-defaults.json's and the item
  schema's, its authority values that schema's enum, its required fields that schema's, its recommended fields the six R-3
  names, each test citing a requirement that exists, and each stage owned by the producer or the assembler;
- every requirement exercised by at least one case, except those listed in UNTESTABLE;
- SPEC.md, the normative text: each block between `generated` markers equal to what contract/requirements.json,
  contract/model.json and examples/profiles.json write there, its draft date the newest revision's in CHANGES.md, whose
  revisions run newest first, its sections 1 to 6 in order with each requirement once in its own, and every file it
  links beside it;
- guides/producers.md and guides/assemblers.md: each block between `generated` markers equal to what the contract files
  and implementations/ write there, every requirement and snake_case identifier they cite defined by the contract, and
  every file they link in this repository.

- implementations/: every entry listed in index.json, stored whole as conformance/import_report.py writes it, from a
  clean checkout, valid against the report schema of the commit it ran against, with the digests that commit's cases
  had when the report names this repository; and the status claims each fitting its requirement's scope.

--implementations also prints how many published cases each listed implementation passes, counted as conformance/README.md
(Reporting results) says: a case changed or published since the run does not count.

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
if "date-time" not in FormatChecker.checkers:  # pragma: no cover
    sys.exit("check.py needs rfc3339-validator, so that format: date-time is asserted (conformance/README.md, Timestamps): pip install rfc3339-validator")

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
    if isinstance(value, int) and not isinstance(value, bool):
        # Python reads an integer literal exactly, however long; as a double it must still be finite (I-JSON).
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
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
    if renderer in ("cwa-messages/v1", "cwa-message-blocks/v1"):  # the blocks renderer realizes the same placements
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
    if (p["route"], p["route_policy_version"]) not in have: problem(f"profile {p['id']} names route policy {p['route']}/{p['route_policy_version']}, which the registry does not hold, so no valid snapshot can carry it")


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


# ---------------------------------------------------------------------------------------------- model
# contract/model.json holds the lists the Spec page shows, in its order; that order is not the schema's, so slots and
# required fields are compared as sets.
model = load("contract/model.json")
item_schema = schemas["https://contextwindowarchitecture.io/schema/context_item.schema.json"]
MODEL_SHAPE = {"planes": ["id", "name", "answers"], "slots": ["id", "holds", "rule"], "authority": ["name", "value", "text"],
               "conflicts": ["when", "then"], "stages": ["name", "owner", "text"], "tests": ["name", "text", "requirement"]}
if sorted(model) != sorted([*MODEL_SHAPE, "item_fields"]): problem(f"contract/model.json: members {sorted(model)}")
for name, keys in MODEL_SHAPE.items():
    for row in model.get(name, []):
        if sorted(row) != sorted(keys) or not all(isinstance(row[k], str) and row[k].strip() for k in keys): problem(f"contract/model.json {name}: {row.get(keys[0])!r} needs exactly {keys}, each a non-blank string")
fields = model.get("item_fields", {})
if sorted(fields) != ["described", "must", "should"]: problem("contract/model.json item_fields: needs must, should and described")
planes = [p.get("id") for p in model.get("planes", [])]
slots = [s.get("id") for s in model.get("slots", [])]
if len(planes) != len(set(planes)) or len(slots) != len(set(slots)): problem("contract/model.json repeats a plane or a slot")
if set(slots) != set(slot_defaults) or set(slots) != set(item_slots): problem(f"contract/model.json slots differ from contract/slot-defaults.json and context_item.schema.json's slot enum: {sorted(set(slots) ^ set(item_slots))}")
for s in slots:
    if str(s).split(".")[0] not in planes: problem(f"contract/model.json slot {s}: its plane is not one of {planes}")
for p in planes:
    if not any(str(s).startswith(p + ".") for s in slots): problem(f"contract/model.json plane {p}: holds no slot")
if [a.get("value") for a in model.get("authority", [])] != item_schema["properties"]["authority"]["enum"]: problem("contract/model.json authority values differ from context_item.schema.json's authority enum, in content or order")
if sorted(fields.get("must", [])) != sorted(item_schema["required"]): problem("contract/model.json item_fields.must differs from context_item.schema.json's required fields")
if fields.get("should") != POLICY_FIELDS: problem(f"contract/model.json item_fields.should is not the six policy fields of R-3, in order: {POLICY_FIELDS}")
for f in fields.get("described", []):
    if sorted(f) != ["key", "text"]: problem(f"contract/model.json item_fields.described: {f.get('key')!r} needs exactly key and text")
for t in model.get("tests", []):
    if t.get("requirement") not in texts: problem(f"contract/model.json test {t.get('name')!r}: cites {t.get('requirement')}, which does not exist")
for s in model.get("stages", []):
    if s.get("owner") not in ("producer", "assembler"): problem(f"contract/model.json stage {s.get('name')!r}: owner {s.get('owner')!r} is neither producer nor assembler")


# ---------------------------------------------------------------------------------------------- SPEC.md
# SPEC.md is written by hand, except the blocks between its generated markers. Each is written here the way
# scripts/spec-markdown.mjs reads the same list back from the Spec page, so the page and this file can be compared.
SECTIONS = {"model": 2, "gov": 3, "fit": 4, "prof": 5, "trace": 6}
RULE_LISTS = {"rulesModel": "model", "rulesGov": "gov", "rulesFit": "fit", "rulesProf": "prof", "rulesTrace": "trace"}
GENERATED = re.compile(r"<!-- generated:(\w+) -->\n\n([\s\S]*?)\n\n<!-- /generated:\1 -->")
md = lambda text: re.sub(r"[\\*<]", lambda m: "\\" + m.group(0), text)
code = lambda text: f"`{text}`"
names = lambda fields: ", ".join(code(f) for f in fields)
def md_table(head, rows):
    return "\n".join("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in [head, ["---"] * len(head), *rows])

def generated_blocks():
    ordered = sorted(requirements, key=lambda r: int(r["id"][2:]))
    plane_slots = lambda p: [s["id"] for s in model["slots"] if s["id"].split(".")[0] == p["id"]]
    return {
        "index": md_table(["Requirement", "Keyword", "Summary"], [[r["id"], r["keyword"], md(r["summary"])] for r in ordered]),
        "planes": md_table(["Plane", "Answers", "Slots"], [[p["name"], md(p["answers"]), names(plane_slots(p))] for p in model["planes"]]),
        "slots": "\n".join(f"- {code(s['id'])}: {md(s['holds'])} {md(s['rule'])}" for s in model["slots"]),
        "mustFields": names(fields["must"]),
        "shouldFields": names(fields["should"]),
        "itemFields": "\n".join(f"- **{md(f['key'])}**: {md(f['text'])}" for f in fields["described"]),
        "authority": md_table(["Role", "Authority", "Meaning"], [[md(a["name"]), code(a["value"]), md(a["text"])] for a in model["authority"]]),
        "conflicts": md_table(["When", "Then"], [[md(c["when"]), md(c["then"])] for c in model["conflicts"]]),
        "stages": "\n".join(f"{i}. **{md(s['name'])}**: {md(s['text'])}" for i, s in enumerate(model["stages"], 1)),
        "tests": md_table(["Test", "What it shows", "Requirement"], [[md(t["name"]), md(t["text"]), t["requirement"]] for t in model["tests"]]),
        **{name: "\n\n".join(f"### {r['id']}: {md(r['summary'])}\n\n{md(r['text'])}" for r in ordered if r["section"] == section)
           for name, section in RULE_LISTS.items()},
        "profile": "```json\n" + json.dumps(load("examples/profiles.json")[0], indent=2, ensure_ascii=False) + "\n```",
    }

js = lambda v: "null" if v is None else "true" if v is True else "false" if v is False else str(v)  # as JavaScript's String()
def plain_table(head, rows): return md_table(head, [[js(c) for c in row] for row in rows])

def guide_blocks():
    """The blocks between generated markers in guides/: what the guide for producers and the guide for assemblers list."""
    ordered = sorted(requirements, key=lambda r: int(r["id"][2:]))
    scopes = load("contract/assembler-scope.json")
    plane = {p["id"]: p["name"] for p in model["planes"]}
    holds = {s["id"]: s["holds"] for s in model["slots"]}
    reason_table = lambda kind: plain_table(["Code", "Rule", "When"], [[code(r["code"]), r["rule"], r["text"]] for r in reasons if r["kind"] == kind])
    listed = [(i, load(f"implementations/{i['id']}.json")) for i in load("implementations/index.json")]
    return {
        "guides/producers.md": {
            "stages": "\n".join(f"{n}. {s['name']} ({s['owner']}): {s['text']}" for n, s in enumerate(model["stages"], 1)),
            "batch": "```json\n" + json.dumps(load("examples/producer-batch.json"), indent=2, ensure_ascii=False) + "\n```",
            "slots": plain_table(["Slot", "Plane", "Holds", "Authority", "Tier", "Lineage", "injection_risk", "conflict_policy"],
                                 [[code(slot), plane[slot.split(".")[0]], holds[slot], code(d["authority"]), d["tier"], d["lineage"], d["injection_risk"], d["conflict_policy"]] for slot, d in slot_defaults.items()]),
            "authority": plain_table(["Authority", "Role", "Meaning"], [[code(a["value"]), a["name"], a["text"]] for a in model["authority"]]),
            "exclusions": reason_table("exclusion"),
        },
        "guides/assemblers.md": {
            "refusals": reason_table("refusal"),
            "scope": plain_table(["Rule", "Summary", "Scope", "What an assembler checks"], [[r["id"], r["summary"], s["scope"], s["note"]] for r, s in zip(ordered, scopes)]),
            "implementations": plain_table(["Language", "Package", "Repository"], [[i["label"], f"{code(e['report']['implementation']['name'])} {e['report']['implementation']['version']}",
                                                                                  f"https://github.com/{e['source']['repository']}"] for i, e in listed]),
        },
    }

def rewrite_blocks(path, want, write):
    """Rewrites a file's generated blocks to what want holds; returns the text it holds afterwards, or holds now."""
    text = read(path)
    found = [m.group(1) for m in GENERATED.finditer(text)]
    if sorted(found) != sorted(want): problem(f"{path}'s generated blocks are {found}; it needs one each of {sorted(want)}")
    rewritten = GENERATED.sub(lambda m: f"<!-- generated:{m.group(1)} -->\n\n{want.get(m.group(1), m.group(2))}\n\n<!-- /generated:{m.group(1)} -->", text)
    if rewritten != text:
        stale = [n for n, body in GENERATED.findall(text) if n in want and body != want[n]]
        if write: open(os.path.join(ROOT, path), "w", encoding="utf-8").write(rewritten); print(f"wrote {path}'s generated blocks")
        else: problem(f"{path} differs from the contract files at {', '.join(stale)}; run check.py --write")
    return rewritten if write else text

def check_guides(write):
    """The guides' generated blocks current, and every requirement and identifier they cite defined by the contract."""
    defined = "\n".join([*(json.dumps(s) for s in schemas.values()), *(read(f) for f in ("contract/reasons.json", "contract/slot-defaults.json", "contract/requirements.json", "conformance/README.md"))])
    for path, want in guide_blocks().items():
        text = rewrite_blocks(path, want, write)
        for n in re.findall(r"\bR-(\d+)\b", text):
            if not 1 <= int(n) <= len(requirements): problem(f"{path} cites R-{n}, which does not exist")
        for name in sorted(set(re.findall(r"`([a-z]+(?:_[a-z0-9]+)+)`", text))):
            if name not in defined: problem(f"{path} names {name}, which the contract does not define")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if not re.match(r"^[a-z]+:|^#", target) and not os.path.exists(os.path.join(ROOT, os.path.dirname(path), target.split("#")[0])):
                problem(f"{path} links {target}, which is not in this repository")


def check_or_write(write):
    spec, changes = read("SPEC.md"), read("CHANGES.md")
    want = generated_blocks()
    found = [m.group(1) for m in GENERATED.finditer(spec)]
    if sorted(found) != sorted(want): problem(f"SPEC.md's generated blocks are {found}; it needs one each of {sorted(want)}")
    dates = re.findall(r"^## (\d{4}-\d{2}-\d{2})\b", changes, re.M)
    if not dates: problem("CHANGES.md has no revision"); return
    if dates != sorted(dates, reverse=True): problem("CHANGES.md: revisions are not newest first")
    if not re.search(r"^Draft of \d{4}-\d{2}-\d{2},", spec, re.M): problem("SPEC.md: no 'Draft of <date>,' line")
    rewritten = GENERATED.sub(lambda m: f"<!-- generated:{m.group(1)} -->\n\n{want.get(m.group(1), m.group(2))}\n\n<!-- /generated:{m.group(1)} -->", spec)
    rewritten = re.sub(r"^Draft of \d{4}-\d{2}-\d{2},", f"Draft of {dates[0]},", rewritten, count=1, flags=re.M)
    if rewritten != spec:
        if write:
            open(os.path.join(ROOT, "SPEC.md"), "w", encoding="utf-8").write(rewritten); print("wrote SPEC.md's generated blocks and draft date")
        else:
            stale = [n for n, body in GENERATED.findall(spec) if n in want and body != want[n]]
            problem(f"SPEC.md differs from the contract files{' at ' + ', '.join(stale) if stale else ''} or from CHANGES.md's newest date; run check.py --write")
    text = rewritten if write else spec
    headings = [(int(m.group(1)), m.start()) for m in re.finditer(r"^## (\d) ", text, re.M)]
    if [n for n, _ in headings] != [1, 2, 3, 4, 5, 6]: problem(f"SPEC.md: sections are {[n for n, _ in headings]}, not 1 to 6 in order")
    section_at = lambda at: next((n for n, start in reversed(headings) if start < at), None)
    for m in GENERATED.finditer(text):
        if m.group(1) in RULE_LISTS and section_at(m.start()) != SECTIONS[RULE_LISTS[m.group(1)]]:
            problem(f"SPEC.md: the {m.group(1)} block is not in section {SECTIONS[RULE_LISTS[m.group(1)]]}")
    held = re.findall(r"^### (R-\d+):", text, re.M)
    if sorted(held) != sorted(rule_ids): problem(f"SPEC.md holds requirements {sorted(set(held) ^ set(rule_ids))} other than once each")
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^[a-z]+:|^#", target): continue
        if not os.path.exists(os.path.join(ROOT, target.split("#")[0])): problem(f"SPEC.md links {target}, which is not beside it")


# ---------------------------------------------------------------------------------------------- implementations
# implementations/ holds each listed implementation's report as conformance/import_report.py stored it, and the Python
# reference assembler's status claims. Counts are never stored: --implementations prints them from the cases as they are now.
import import_report  # noqa: E402

def implementations():
    index = load("implementations/index.json")
    ids = [i.get("id") for i in index]
    if len(ids) != len(set(ids)) or any(sorted(i) != ["id", "label"] or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", i["id"]) or not i["label"].strip() for i in index):
        problem("implementations/index.json: each entry needs a distinct lowercase id and a label")
    allowed = {"index.json", *(f"{i}.json" for i in ids), *(f"{i}.status.json" for i in ids)}
    for name in sorted(os.listdir(os.path.join(ROOT, "implementations"))):
        if name not in allowed: problem(f"implementations/{name}: not an entry implementations/index.json lists")
    entries = {}
    for i in ids:
        path = f"implementations/{i}.json"
        if not os.path.exists(os.path.join(ROOT, path)): problem(f"{path}: implementations/index.json lists {i}, which has no report"); continue
        entries[i] = load(path)
        for p in import_report.entry_problems(entries[i], ROOT): problem(f"{path}: {p}")
        status = f"implementations/{i}.status.json"
        if os.path.exists(os.path.join(ROOT, status)):
            for p in import_report.status_problems(load(status), load("contract/assembler-scope.json")): problem(f"{status}: {p}")
    return index, entries

def print_implementations(index, entries):
    published = import_report.case_digests_now(ROOT)
    for i in index:
        if i["id"] not in entries: continue
        outcomes = list(import_report.tally(entries[i["id"]]["report"], entries[i["id"]]["cases_at_run"], published).values())
        note = ", ".join(f"{outcomes.count(k)} {k}" for k in ("stale", "failed", "not run") if outcomes.count(k))
        print(f"{i['label']}: {outcomes.count('passed')} of {len(outcomes)} published cases and rejections pass{'; ' + note if note else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite SPEC.md's generated blocks and draft date")
    ap.add_argument("--implementations", action="store_true", help="print how many published cases each listed implementation passes")
    args = ap.parse_args()
    check_or_write(args.write)
    check_guides(args.write)
    index, entries = implementations()
    if args.implementations: print_implementations(index, entries)
    print(f"{len(case_dirs)} cases, {len(rejection_dirs)} rejections, {len(requirements)} requirements, {len(reasons)} reason codes")
    for w in warnings: print("warning:", w)
    for p in problems: print("PROBLEM:", p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)

if __name__ == "__main__":
    main()
