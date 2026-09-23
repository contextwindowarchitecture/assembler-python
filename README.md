# cwa-assembler

Reference assembler for the [Context Window Architecture](https://contextwindowarchitecture.io) draft specification. It turns a frozen snapshot of candidate items into a rendered payload and a trace, without calling a model or reading anything outside the snapshot.

**Status: M12 invalid-snapshot rejection done; every checkable requirement is claimed; not released.** Every candidate is admitted or excluded with exactly one registered reason, following the spec's precedence. Items over their own `token_budget` are reduced, then slots over the route's `max_tokens` shed their own items, then admitted items are shed, never taking a slot below the route's `min_tokens`, in tier order and by the route's fitting policy until the rendered payload fits (charged `budget.margin_percent` more when the snapshot reserves a margin for an estimating tokenizer), and assemblies that would break a requirement are refused with a trace and no payload: a missing required slot, protected content over budget, a payload that fits only by breaking a slot floor, or too little evidence, with a recovery action. Declared conflict groups are resolved as the spec directs, and in the slots a route asks, stale observations are then superseded by the latest from the same producer and source (R-25), exact duplicate bodies (equal once whitespace runs collapse) are excluded (R-24) beside the near-duplicates retrievers report dropping (R-13), and each producer and source keeps at most `max_per_source` items (R-26); none of these stages ever excludes a protected item or a conflict-group member. Instruction groups are decided by authority or by peers' `conflict_policy`, and fact groups by the route's precedence of authenticated producers, with an optional freshness tie-break. Losers are excluded, and a group with no unique supported resolution is surfaced (marked in the payload) or refused with `conflict_unresolved`, as the route directs. A snapshot whose profile is for another route, or does not place the instructions, the query and, on a parser route, the output contract, is rejected before assembly (R-20). Items in slots the profile does not place are excluded, and an admitted protected item there refuses with `protected_slot_unplaced`. Two tokenizers are built: `fixture-whitespace/v1`, the conformance fixture, and `estimate-utf8/v1`, UTF-8 bytes divided by 4, rounded up, a portable estimate for models with no local tokenizer, meant for use with a margin. Two renderers are built: `fixture-xml/v1`, the plain-text conformance fixture, and `cwa-messages/v1`, the render IR a provider adapter consumes. In the IR, governance takes the system and tools channels, and everything else, prior turns included, is escaped material in the single user message (R-7, R-10). Profiles and route policies can be pinned by digest in a registry lock, so content cannot change under an unchanged version, and a deployment gets only evaluated profiles (R-19, R-20). Assembly is deterministic across processes, hash seeds, time zones and locales, and across languages where the spec pins the rules: strings order by UTF-16 code units, blank means ECMAScript whitespace, timestamps follow a portable RFC 3339 profile, and `context.snapshot_digest` is a defined RFC 8785 digest. Every trace names the specification its profile was written for (`context.spec`, `cwa/draft` until the first release; a profile for another specification is rejected with the snapshot), uses registered reason codes, records each included item's eligibility, and carries stage timings only when you lend `assemble()` a clock. All forty-four published conformance cases pass byte for byte, and all fourteen rejection cases are rejected: a snapshot that fails its schemas or a snapshot check raises `SnapshotError` listing the problems, with no payload and no trace (R-17). [conformance-report.json](conformance-report.json) records each outcome. [status.json](status.json) lists what is claimed per requirement and the tests behind each claim. See [docs/DESIGN.md](docs/DESIGN.md) for the design and milestones.

## Use

```python
from cwa import Snapshot, assemble

snapshot = Snapshot.from_json(document)   # snapshot.schema.json; validated and copied
result = assemble(snapshot)               # pure: no I/O, clock or model

result.payload    # bytes, or None when refused
result.trace      # dict matching trace.schema.json
snapshot.digest() # SHA-256 of the RFC 8785 form, the replay key

assemble(snapshot, clock=time.perf_counter).trace["timings"]   # stage timings, only from a clock you lend
```

Count with your own tokenizer by passing it in. Any object with an `id` and a `count(text)` satisfies `cwa.Tokenizer`. It joins the built-in ones for that call only, and cannot reuse a built-in id. Load its data (an encoding file, a vocabulary) before freezing: `assemble()` reads nothing else. If it estimates, reserve headroom with `budget.margin_percent`. [examples/tiktoken_tokenizer.py](examples/tiktoken_tokenizer.py) is an exact adapter for OpenAI encodings, kept outside the package:

```python
from cwa import Snapshot, assemble

class Chars:
    id = "my-chars/v1"
    def count(self, text): return len(text)

snapshot = Snapshot.from_json(document, tokenizers={Chars.id: Chars()})   # document["tokenizer"] == "my-chars/v1"
snapshot = Snapshot.freeze(**fields, tokenizers={Chars.id: Chars()})     # the keyword form takes it too
```

Load profiles and route policies through the registry, so an edit under an unchanged version is caught before it reaches a snapshot:

```python
from cwa.registry import Registry, lock

pinned = lock(profiles, route_policies)                     # or lock(new, existing=pinned) to add versions
registry = Registry.from_json(pinned, profiles, route_policies)
profile = registry.profile("policy-first-chat", 1, deployment=True)   # evaluated profiles only
snapshot = Snapshot.freeze(profile=profile, route_policy=registry.route_policy("support-chat", "v1"), ...)
```

## Develop

```sh
uv sync
uv run pytest
uv run python -m cwa.conformance > conformance-report.json   # regenerate the committed report
```

The package ships `py.typed`, and the suite runs mypy over `src/cwa`, so its annotations stay usable by your type checker. [conformance-report.json](conformance-report.json) records each published case's outcome, and each rejection case's, in the website's `conformance_report.schema.json` format; a test fails when it is stale.

## The contract is vendored

Schemas, slot defaults, reason codes and conformance cases come from the website repository, which owns the spec. They are copied into `src/cwa/contract/data/` and `conformance/`, and every file is pinned by SHA-256 in `contract.lock.json`. Don't edit them here; change them in the website repo, then:

```sh
python scripts/vendor_contract.py --website ../website          # re-vendor and rewrite the lock
python scripts/vendor_contract.py --website ../website --check  # fail on drift
```

## License

Apache License 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE). The vendored contract comes from the website repository under the same license.
