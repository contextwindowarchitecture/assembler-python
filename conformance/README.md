# CWA conformance cases

Language-neutral test cases for assemblers. Each directory under `cases/` holds:

| File | Contents |
| --- | --- |
| `case.json` | `id`, the requirement IDs the case exercises (`rules`), and a one-sentence `description` |
| `snapshot.json` | The frozen assembly input, valid against `schema/snapshot.schema.json` |
| `expected.trace.json` | The trace a conformant assembler emits, valid against `schema/trace.schema.json` |
| `expected.payload.txt` | The exact rendered payload bytes; absent when the case expects a refusal |

Some cases have a generator in `generators/`. It holds a table of each candidate's intended outcome, and it derives the expected trace and payload from that table rather than from any assembler's logic. Regenerate a case with `python3 conformance/generators/<case>.py`, and review the diff.

## Running a case

1. Validate `snapshot.json` against the snapshot schema and load it. Resolve `tokenizer` and `renderer` by ID; an implementation that does not provide one skips the case and reports it as skipped, not passed.
2. Assemble.
3. Compare the payload byte for byte with `expected.payload.txt`, or confirm no payload when that file is absent.
4. Compare the trace with `expected.trace.json` after removing `trace_id`, `timings` and `context.snapshot_digest`. Trace IDs and timings may differ (R-23). Snapshot digests depend on an implementation's canonical serialization, which the spec does not yet fix.

Array order in the trace is part of the expectation:

- `included[]` follows payload order.
- `excluded[]` lists producer-stage rows first, ordered by producer id and then `item_id`. Assembler rows follow in pipeline order. Admission rows are ordered by producer id and then recorded `item_id`. Later stages define their order when they are specified.
- `defaults_filled[]` is ordered by `item_id`, then by field in R-3 order: `token_budget`, `variants`, `conflict_policy`, `lineage`, `eligibility`, `injection_risk`. It covers every schema-valid item from a producer the route admits, including items later excluded, because later admission checks read the filled values.

When an item fails several admission checks, the trace records the earliest applicable code in `contract/reasons.json` order (R-21).

## Fixture tokenizer and renderer

- `fixture-whitespace/v1` counts maximal runs of characters outside the ECMAScript whitespace and line-terminator set: U+0009–U+000D, U+0020, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. This is what JavaScript's `/\S+/gu` matches. Other languages must use this set explicitly; Python's `\S`, for example, differs at U+001C–U+001F and U+FEFF. It is a test fixture, not a model tokenizer.
- `fixture-xml/v1` renders each placed item as `<{tag} id="{id}">\n{body}\n</{tag}>\n`, where `{tag}` is the placement's `wrap` without its `xml:` prefix, in profile placement order. Within a placement it orders items by `id`. It escapes `&`, `<` and `>` in bodies, and additionally `"` in attribute values. It supports only `xml:` wraps. Per-item `tokens` count the rendered body; wrapper tokens appear only in `result.input_tokens`.

Implementations vendor these cases pinned by hash, so a case changes only through a reviewed edit here.
