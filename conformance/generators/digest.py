"""context.snapshot_digest as conformance/README.md, Snapshot digest defines it: normalize, then
take the SHA-256 of the RFC 8785 serialization. Imported by the generators; run directly, it
prints the digest of each case's snapshot.json."""
import copy, hashlib, json, math, os, re, sys

NONBLANK = re.compile(r"[^\t\n\v\f\r    -     　﻿]")
U16 = lambda s: s.encode("utf-16-be")


def jcs(value):
    """RFC 8785 for the JSON a snapshot can hold."""
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        assert math.isfinite(value)
        if value == int(value) and abs(value) < 1e21:
            return str(int(value))
        text = repr(value)  # shortest round trip, as ECMAScript; exponents need its spelling
        if "e" in text:
            mantissa, exponent = text.split("e")
            text = f"{mantissa}e{'+' if int(exponent) > 0 else '-'}{abs(int(exponent))}"
        return text
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(jcs(v) for v in value) + "]"
    return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + jcs(value[k]) for k in sorted(value, key=U16)) + "}"


def usable(item):
    return isinstance(item, dict) and isinstance(item.get("id"), str) and bool(NONBLANK.search(item["id"]))


def normalize(snapshot):
    s = copy.deepcopy(snapshot)
    for batch in s["batches"]:
        named = sorted((i for i in batch["items"] if usable(i)), key=lambda i: (U16(i["id"]), jcs(i).encode()))
        batch["items"] = named + [i for i in batch["items"] if not usable(i)]
        batch["excluded"].sort(key=lambda r: (U16(r["item_id"]), jcs(r).encode()))
    s["batches"].sort(key=lambda b: U16(b["producer"]["id"]))
    s["conflicts"].sort(key=lambda g: U16(g["id"]))
    for group in s["conflicts"]:
        group["items"].sort(key=U16)
    return s


def snapshot_digest(snapshot):
    return hashlib.sha256(jcs(normalize(snapshot)).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    web = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    cases = os.path.join(web, "conformance/cases")
    for name in sorted(os.listdir(cases)):
        print(name, snapshot_digest(json.load(open(os.path.join(cases, name, "snapshot.json")))))
