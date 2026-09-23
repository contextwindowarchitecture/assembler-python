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

1. Validate `snapshot.json` against the snapshot schema and load it. Resolve `tokenizer` and `renderer` by ID; an implementation that does not provide one skips the case and reports it as skipped, not passed. A snapshot that fails the schema is rejected before assembly and has no trace; the refusal codes describe assemblies of valid snapshots.
2. Assemble.
3. Compare the payload byte for byte with `expected.payload.txt`, or confirm no payload when that file is absent.
4. Compare the trace with `expected.trace.json` after removing `trace_id`, `timings` and `context.snapshot_digest`. Trace IDs and timings may differ (R-23). Snapshot digests depend on an implementation's canonical serialization, which the spec does not yet fix.

Array order in the trace is part of the expectation:

- `included[]` follows payload order.
- `excluded[]` lists producer-stage rows first, ordered by producer id and then `item_id`. Assembler rows follow in pipeline order. Admission rows are ordered by producer id and then recorded `item_id`. Fitting rows follow in the order items were omitted. Later stages define their order when they are specified.
- `compressed[]` has one row per included occurrence of a compressed item, in payload order.
- Assembler rows in `excluded[]` carry `slot` whenever the candidate names one of the eleven slots, even when it fails for another reason (R-22). Producer rows carry what the producer reported, which has no slot.
- `defaults_filled[]` is ordered by `item_id`, then by field in R-3 order: `token_budget`, `variants`, `conflict_policy`, `lineage`, `eligibility`, `injection_risk`. It covers every schema-valid item from a producer the route admits, including items later excluded, because later admission checks read the filled values.

When an item fails several admission checks, the trace records the earliest applicable code in `contract/reasons.json` order (R-21).

## Refusals

A refused trace has `result: null`, `included: []` and `compressed: []` (R-17). It keeps the producer and admission rows in `excluded[]`, and `defaults_filled[]`. An `evidence_required` refusal comes after fitting, so it also keeps the fitting rows. Assembly checks the refusal conditions in `contract/reasons.json` order and records the first that holds (R-21):

1. `required_slot_missing`: no admitted item in `governance.instructions` or `interaction.query`, or, on a route with `parser: true`, in `governance.output_contract` (R-4).
2. `conflict_unresolved`: specified with conflict resolution.
3. `protected_content_over_budget`: the payload rendered from the protected items alone exceeds `budget.input` (R-17). Nothing is shed first, so the trace has no `over_budget` rows.
4. `evidence_required`: after fitting, a route with `requires_evidence: true` includes no `evidence.knowledge` or `evidence.tool_results` item, or fewer items in an evidence slot than that slot's `min_included` (R-12). `recovery.action` is:
   - `request_context` when no evidence item was omitted for budget, so the shortfall came from producers or admission;
   - `precompute_summary` when an evidence item omitted for budget had no variants;
   - `retrieve_narrower` otherwise: every evidence item omitted for budget had variants, and they did not fit.

## Fitting

Fitting reduces the admitted items the profile places until the payload fits (R-16). The payload *fits* when the whole payload, rendered and counted with the declared tokenizer, is at most `budget.input`. An implementation may estimate, but it must reach the same decisions. An item's tier is its own `tier` when it sets one, and otherwise its slot's default raised by the route's `tier_upgrades`.

1. If the protected items alone do not fit, refuse with `protected_content_over_budget`.
2. While the payload does not fit, omit droppable items one at a time, in shedding order.
3. While it still does not fit, reduce compressible items step by step. The route's `fitting_order` steps come first. Then come a `compress` step for each slot, in shedding order, and an `omit` step for each slot, in shedding order, skipping any step the route listed. A step visits the slot's compressible items from the lowest rank up and stops as soon as the payload fits.
   - `compress` replaces an item's body with a supplied variant whose rendered body has fewer tokens than the item's own. It picks the variant with the most tokens that makes the payload fit, or, when none does, the one with the fewest. Among variants with equal counts, the earlier one in `variants` wins. An item with no shorter variant is left as it is.
   - `omit` removes the item, compressed or not.
4. Protected items are never compressed, truncated or omitted.

*Shedding order* takes slots by ascending `priority` (default 0), then by slot name, and within each slot takes items from the lowest rank up. Rank sorts by the slot's `order_by` keys, then by `id`, with the first item ranked highest. The default keys are `["-relevance", "-freshness"]`: higher scores rank first and unscored items last, then newer items first.

Fitting decides per item. A slot the profile places twice sheds or compresses both occurrences together. Each omitted item adds one `excluded[]` row with reason `over_budget`, stage `assembler` and its slot. Each included occurrence of a compressed item adds one `compressed[]` row: `from` counts the rendered original body, `to` and `included[].tokens` count the rendered variant, and `method` and `variant_id` name the variant (R-18). Per-item `token_budget` caps are not specified yet, and no case sets a cap its item exceeds.

## Fixture tokenizer and renderer

- `fixture-whitespace/v1` counts maximal runs of characters outside the ECMAScript whitespace and line-terminator set: U+0009–U+000D, U+0020, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. This is what JavaScript's `/\S+/gu` matches. Other languages must use this set explicitly; Python's `\S`, for example, differs at U+001C–U+001F and U+FEFF. It is a test fixture, not a model tokenizer.
- `fixture-xml/v1` renders each placed item as `<{tag} id="{id}">\n{body}\n</{tag}>\n`, where `{tag}` is the placement's `wrap` without its `xml:` prefix, in profile placement order. Within a placement it orders items by `id`. It escapes `&`, `<` and `>` in bodies, and additionally `"` in attribute values. It supports only `xml:` wraps. Per-item `tokens` count the rendered body; wrapper tokens appear only in `result.input_tokens`.

Implementations vendor these cases pinned by hash, so a case changes only through a reviewed edit here.
