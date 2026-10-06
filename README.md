# contextwindowarchitecture-assembler

Reference assembler for the [Context Window Architecture](https://contextwindowarchitecture.io) draft specification. It turns a frozen snapshot of candidate items into a rendered payload and a trace, without calling a model or reading anything outside the snapshot.

**Status: every release gate is met, M11 to M14 including the TypeScript second implementation; not released.** Every candidate is admitted or excluded with exactly one registered reason, following the spec's precedence: a producer's kind limits its slots whatever the route lists (retrieval and MCP output is evidence, memory producers send only memory, and tools come only from the capability grant's producer listed with kind `capability_policy`), and `untrusted` authority is allowed only in tool results, memory and history. Items over their own `token_budget` are reduced, then slots over the route's `max_tokens` shed their own items, then admitted items are shed, never taking a slot below the route's `min_tokens`, in tier order and by the route's fitting policy until the rendered payload fits (charged `budget.margin_percent` more when the snapshot reserves a margin for an estimating tokenizer), and assemblies that would break a requirement are refused with a trace and no payload: a missing required slot, protected content over budget, a payload that fits only by breaking a slot floor, or too little evidence, with a recovery action. Declared conflict groups are resolved as the spec directs, and in the slots a route asks, stale observations are then superseded by the latest from the same producer and source (R-25), exact duplicate bodies (equal once whitespace runs collapse) are excluded (R-24) beside the near-duplicates retrievers report dropping (R-13), and each producer and source keeps at most `max_per_source` items (R-26); none of these stages ever excludes a protected item or a conflict-group member. Instruction groups are decided by authority or by peers' `conflict_policy`, and fact groups by the route's precedence of authenticated producers, with an optional freshness tie-break. Losers are excluded, and a group with no unique supported resolution is surfaced (marked in the payload) or refused with `conflict_unresolved`, as the route directs. A snapshot whose profile is for another route, or does not place the instructions, the query and, on a parser route, the output contract, is rejected before assembly (R-20). Items in slots the profile does not place are excluded, and an admitted protected item there refuses with `protected_slot_unplaced`. Two tokenizers are built: `fixture-whitespace/v1`, the conformance fixture, and `estimate-utf8/v1`, UTF-8 bytes divided by 4, rounded up, a portable estimate for models with no local tokenizer, meant for use with a margin. Three renderers are built: `fixture-xml/v1`, the plain-text conformance fixture, `cwa-messages/v1`, the render IR a provider adapter consumes, and `cwa-message-blocks/v1`, which the conformance README lists as optional: the same request, with the user message's content split into one entry per item placed there, so an application can put a provider's cache breakpoint at any item boundary, and sized as the sum of every entry's count. In the IR, governance takes the system and tools channels, where a surfaced conflict member's mark wraps its entry's text, since that text is all the model receives, and everything else, prior turns included, is escaped material in the single user message (R-7, R-10, R-11). Within a placement items render by id, except prior turns, which render in the order they were said: by `freshness`, compared as instants at full precision, and by id only among turns said at the same instant (R-7). Profiles and route policies can be pinned by digest in a registry lock, so content cannot change under an unchanged version, and a deployment gets only evaluated profiles (R-19, R-20). Assembly is deterministic across processes, hash seeds, time zones and locales, and across languages where the spec pins the rules: strings order by UTF-16 code units, blank means ECMAScript whitespace, timestamps follow a portable RFC 3339 profile, every number is read as a double (so an integer beyond 2^53 compares as JavaScript reads it), and `context.snapshot_digest` is a defined RFC 8785 digest. Every trace names the specification its profile was written for (`context.spec`, `cwa/draft` until the first release; a profile for another specification is rejected with the snapshot), uses registered reason codes, records each included item's eligibility, and carries stage timings only when you lend `assemble()` a clock. All sixty-one published conformance cases pass byte for byte, and all twenty-five rejection cases are rejected, with none skipped: a snapshot that fails its schemas or a snapshot check, or holds a string or number RFC 8785 cannot serialize, raises `SnapshotError` listing the problems, with no payload and no trace (R-17). A tokenizer or renderer this assembler does not provide is no problem with the snapshot, so it is not rejected for one: once every check that can run without it passes, it raises `UnsupportedComponentError`. [conformance-report.json](conformance-report.json) records each outcome. [status.json](status.json) lists what is claimed per requirement and the tests behind each claim. See [docs/DESIGN.md](docs/DESIGN.md) for the design and milestones.

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

`Snapshot.from_json` and `Snapshot.freeze` reject a snapshot that fails its schemas or a snapshot check with `SnapshotError`, whose `problems` say what is wrong (R-17). A tokenizer or renderer this assembler does not provide is not a problem with the snapshot, so a snapshot naming one is not rejected for it: the call raises `cwa.UnsupportedComponentError` instead, a `LookupError` whose `component` is `"tokenizer"` or `"renderer"` and whose `id` is the id the snapshot names. It comes only after every check that can run without that component passes. Every check but the renderer's own runs before a renderer is needed, and no check needs a tokenizer, so an invalid snapshot is still rejected, whatever it names. A snapshot lacking both components names the renderer, since its check needs it first. Either way, assembly never starts: there is no payload and no trace.

Count with your own tokenizer by passing it in. Any object with an `id` and a `count(text)` satisfies `cwa.Tokenizer`. Pass it under its own `id`, which is the name the trace gives it; it joins the built-in ones for that call only. It cannot take the id of a tokenizer the conformance README publishes, which today are the two built-in ones, since a trace that names a published tokenizer must mean its published count (R-16). `Snapshot.from_json` and `Snapshot.freeze` raise `ValueError` for a tokenizer with a published id, or one passed under a key that is not its `id`, before reading the snapshot, so assembly never starts: there is no payload and no trace. Load its data (an encoding file, a vocabulary) before freezing: `assemble()` reads nothing else. If it estimates, reserve headroom with `budget.margin_percent`. [examples/tiktoken_tokenizer.py](examples/tiktoken_tokenizer.py) is an exact adapter for OpenAI encodings, kept outside the package:

```python
from cwa import Snapshot, assemble

class Chars:
    id = "my-chars/v1"
    def count(self, text): return len(text)

snapshot = Snapshot.from_json(document, tokenizers={Chars.id: Chars()})   # document["tokenizer"] == "my-chars/v1"
snapshot = Snapshot.freeze(**fields, tokenizers={Chars.id: Chars()})     # the keyword form takes it too
```

Render with your own renderer the same way, through `renderers=`. Any object with an `id`, a `profile_errors(profile)` and a `render(occurrences)` satisfies `cwa.render.Renderer`. Pass it under its own `id`, which is the name the trace gives it; it joins the built-in ones for that call only. It cannot take the id of a renderer the conformance README publishes, which today are the three built-in ones, `fixture-xml/v1`, `cwa-messages/v1` and the optional `cwa-message-blocks/v1`, since a trace that names a published renderer must mean its published rendering (R-16). `Snapshot.from_json` and `Snapshot.freeze` raise `ValueError` for a renderer with a published id, or one passed under a key that is not its `id`, before reading the snapshot, so assembly never starts: there is no payload and no trace. No published case covers a renderer of your own, and a conformant application renders with one they cover (§1 on the spec page).

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
uv run python scripts/bench.py                                # time assemble() against DESIGN.md §7
```

[CHANGELOG.md](CHANGELOG.md) is generated from the commit history with git-cliff; regenerate it at a release with `uvx git-cliff --tag vX.Y.Z -o CHANGELOG.md`. CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11, 3.12, 3.13 and 3.14, and checks the vendored contract against the website commit `contract.lock.json` pins. Each tag gets a GitHub release once CI passes on the tagged commit (`.github/workflows/release.yml`); its notes name that website commit and list the tag's own commits, written by git-cliff. A tag that is not `vX.Y.Z` is a prerelease, and a tag pushed before the workflow existed is released with `gh workflow run release.yml -f tag=<tag>`.

The package ships `py.typed`, and the suite runs mypy over `src/cwa`, so its annotations stay usable by your type checker. [conformance-report.json](conformance-report.json) records each published case's outcome, and each rejection case's, in the website's `conformance_report.schema.json` format, naming the repository and commit its cases came from, as `contract.lock.json` records them; a test fails when it is stale. The runner skips a case when any tokenizer or renderer it uses and this assembler lacks is optional, and fails it when every one it lacks is among the four the conformance README requires; this assembler provides all four, and the optional `cwa-message-blocks/v1` too. A rejection case always runs through `Snapshot.from_json`, since every check but the renderer's own runs before a renderer is needed and no check needs a tokenizer. It is rejected for any other check it breaks, whatever it names, and skipped only when it stops for an optional renderer this assembler lacks, which leaves that renderer's check as the one it breaks. Stopping for a required renderer, or for a tokenizer after every check has passed, fails it.

## The contract is vendored

Schemas, slot defaults, reason codes and conformance cases come from the website repository, which owns the spec. They are copied into `src/cwa/contract/data/` and `conformance/`, and every file is pinned by SHA-256 in `contract.lock.json`. Don't edit them here; change them in the website repo, then:

```sh
python scripts/vendor_contract.py --website ../website          # re-vendor and rewrite the lock
python scripts/vendor_contract.py --website ../website --check  # fail on drift
```

## License

Apache License 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE). The vendored contract comes from the website repository under the same license.
