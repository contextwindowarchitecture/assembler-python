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

1. Validate `snapshot.json` against the snapshot schema and load it. Resolve `tokenizer` and `renderer` by ID; an implementation that does not provide one skips the case and reports it as skipped, not passed. A snapshot that fails the schema is rejected before assembly and has no trace; the refusal codes describe assemblies of valid snapshots. Conflict groups are part of that check: group ids must be unique, every item id a group names must be the id of a candidate or a producer exclusion in the snapshot, no item may belong to two groups, and a fact group's `fact` must be a key of the route's `facts`. The profile is part of it too (R-20): its `route` and `route_policy_version` must equal the route policy's `route` and `version`, it must place `governance.instructions` and `interaction.query`, and it must place `governance.output_contract` when the route sets `parser: true`.
2. Assemble.
3. Compare the payload byte for byte with `expected.payload.txt`, or confirm no payload when that file is absent.
4. Compare the trace with `expected.trace.json` after removing `trace_id`, `timings` and `context.snapshot_digest`. Trace IDs and timings may differ (R-23). Snapshot digests depend on an implementation's canonical serialization, which the spec does not yet fix.

Array order in the trace is part of the expectation:

- `included[]` follows payload order.
- `excluded[]` lists producer-stage rows first, ordered by producer id and then `item_id`. Assembler rows follow in pipeline order. Admission rows are ordered by producer id and then recorded `item_id`. Conflict rows follow, ordered by `item_id`, and fitting rows follow in the order items were omitted.
- `conflicts[]` has one record per declared group, ordered by `group_id`.
- `compressed[]` has one row per included occurrence of a compressed item, in payload order.
- Assembler rows in `excluded[]` carry `slot` whenever the candidate names one of the eleven slots, even when it fails for another reason (R-22). Producer rows carry what the producer reported, which has no slot.
- `defaults_filled[]` is ordered by `item_id`, then by field in R-3 order: `token_budget`, `variants`, `conflict_policy`, `lineage`, `eligibility`, `injection_risk`. It covers every schema-valid item from a producer the route admits, including items later excluded, because later admission checks read the filled values.

When an item fails several admission checks, the trace records the earliest applicable code in `contract/reasons.json` order (R-21).

The last admission check is placement (R-20). An item whose slot the profile does not place is excluded with `slot_unplaced`, unless it is protected: a protected item is admitted, and assembly then refuses with `protected_slot_unplaced`. An item is protected when its tier is, which is its own `tier` when it sets one and otherwise its slot's default raised by the route's `tier_upgrades`.

## Refusals

A refused trace has `result: null`, `included: []` and `compressed: []` (R-17). It keeps the producer, admission and conflict rows in `excluded[]`, `conflicts[]` and `defaults_filled[]`: conflicts are resolved right after admission, before any refusal check, and resolution never excludes a protected item, so it cannot cause `required_slot_missing`. An `evidence_required` refusal comes after fitting, so it also keeps the fitting rows. Assembly checks the refusal conditions in `contract/reasons.json` order and records the first that holds (R-21):

1. `required_slot_missing`: no admitted item in `governance.instructions` or `interaction.query`, or, on a route with `parser: true`, in `governance.output_contract` (R-4).
2. `protected_slot_unplaced`: an admitted protected item's slot has no placement in the profile (R-20).
3. `conflict_unresolved`: a conflict group escalated, and its action is `request_context` or `refuse` (R-11). `recovery.action` is `request_context` when every such group's action is `request_context`, and the trace has no `recovery` otherwise.
4. `protected_content_over_budget`: a protected item's rendered body exceeds its `token_budget`, or the payload rendered from the protected items alone exceeds `budget.input` (R-17). Nothing is shed first, so the trace has no `over_budget` rows.
5. `evidence_required`: after fitting, a route with `requires_evidence: true` includes no `evidence.knowledge` or `evidence.tool_results` item, or fewer items in an evidence slot than that slot's `min_included` (R-12). `recovery.action` is:
   - `request_context` when no evidence item was omitted for budget, so the shortfall came from producers or admission;
   - `precompute_summary` when an evidence item omitted for budget had no variants;
   - `retrieve_narrower` otherwise: every evidence item omitted for budget had variants, and they did not fit.

## Conflicts

Conflict resolution runs right after admission (R-6, R-11). It acts only on the groups the application declared, and it never reads a body. A group's *members* are the items it names that admission admitted. The trace's `items` lists every id the group names, in `id` order.

**Moot.** A group with fewer than two members changes nothing: `decided_by: moot`, `resolution: moot`.

**Instruction groups.**

1. Only `governing` and `user` authority may instruct. Members with any other authority stay in the payload as material and take no part in the decision.
2. The *peers* are the members at the highest instructing authority present: `governing`, or else `user`. With one peer, or none, the group is decided by authority, and nothing is excluded: `decided_by: authority`, `resolution: resolved`, and `winner` is that peer when there is one.
3. With two or more peers, if exactly one peer's `conflict_policy` is `governs` and every other peer's is `defers`, the deferring peers are excluded with `conflict_deferred`: `decided_by: policy`, `resolution: resolved`, `winner` the governing peer. Any other combination escalates.

**Fact groups** use the route's `facts[<fact>]` policy.

1. A member is *eligible* when the authenticated producer of its batch appears in `precedence` and its `scope` carries every key the policy's `scope` lists.
2. The *leaders* are the eligible members whose producer comes earliest in `precedence`. A single leader wins: `decided_by: policy`. When there are several, the policy has `freshness_tiebreak: true`, and one leader's `freshness` is strictly later than every other leader's, that leader wins: `decided_by: freshness`. Otherwise, and when no member is eligible, the group escalates.
3. Every other member, eligible or not, is excluded with `conflict_lost`. The result has `resolution: resolved` and `winner` the winning member.

**Protected members.** Resolution never excludes a protected item (R-16's tier, as Fitting defines it). A decision that would exclude one escalates instead, and nothing in the group is excluded.

**Escalation.** An escalated group has `decided_by: escalated` and no `winner`. It takes the fact policy's `on_unresolved`, or for instruction groups the route's `on_unresolved_instruction` (default `refuse`):

| Action | `resolution` | Effect |
| --- | --- | --- |
| `surface` | `surfaced` | Every member stays. The renderer marks each occurrence of a member as conflicting. |
| `request_context` | `context_requested` | Assembly refuses with `conflict_unresolved`. |
| `refuse` | `refused` | Assembly refuses with `conflict_unresolved`. |

Each item excluded by a group adds one `excluded[]` row with its reason, stage `assembler` and its slot. Excluded items take no further part in assembly.

## Fitting

Fitting reduces the admitted items the profile places, less any that conflict resolution excluded, until the payload fits (R-16). The payload *fits* when the whole payload, rendered and counted with the declared tokenizer, is at most `budget.input`. An implementation may estimate, but it must reach the same decisions. An item's tier is its own `tier` when it sets one, and otherwise its slot's default raised by the route's `tier_upgrades`.

1. If a protected item's rendered body exceeds its `token_budget`, or the protected items alone do not fit, refuse with `protected_content_over_budget`.
2. Enforce the other items' `token_budget` caps, in shedding order, whether or not the payload fits. A droppable item whose rendered body exceeds its cap is omitted. A compressible one takes the variant with the most tokens whose rendered body is within the cap, the earlier one on ties, and is omitted when there is none. A `null` cap sets no per-item limit.
3. While the payload does not fit, omit droppable items one at a time, in shedding order.
4. While it still does not fit, reduce compressible items step by step. The route's `fitting_order` steps come first. Then come a `compress` step for each slot, in shedding order, and an `omit` step for each slot, in shedding order, skipping any step the route listed. A step visits the slot's compressible items from the lowest rank up and stops as soon as the payload fits.
   - `compress` replaces an item's body with a supplied variant whose rendered body has fewer tokens than its current one: its own body, or the variant its cap chose. It picks the variant with the most tokens that makes the payload fit, or, when none does, the one with the fewest. Among variants with equal counts, the earlier one in `variants` wins. An item with no shorter variant is left as it is.
   - `omit` removes the item, compressed or not.
5. Protected items are never compressed, truncated or omitted.

*Shedding order* takes slots by ascending `priority` (default 0), then by slot name, and within each slot takes items from the lowest rank up. Rank sorts by the slot's `order_by` keys, then by `id`, with the first item ranked highest. The default keys are `["-relevance", "-freshness"]`: higher scores rank first and unscored items last, then newer items first.

Fitting decides per item. A slot the profile places twice sheds or compresses both occurrences together. Each omitted item adds one `excluded[]` row with reason `over_budget`, stage `assembler` and its slot. Each included occurrence of a compressed item adds one `compressed[]` row: `from` counts the rendered original body, `to` and `included[].tokens` count the rendered variant, and `method` and `variant_id` name the variant (R-18).

## Fixture tokenizer and renderer

- `fixture-whitespace/v1` counts maximal runs of characters outside the ECMAScript whitespace and line-terminator set: U+0009–U+000D, U+0020, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. This is what JavaScript's `/\S+/gu` matches. Other languages must use this set explicitly; Python's `\S`, for example, differs at U+001C–U+001F and U+FEFF. It is a test fixture, not a model tokenizer.
- `fixture-xml/v1` renders each placed item as `<{tag} id="{id}">\n{body}\n</{tag}>\n`, where `{tag}` is the placement's `wrap` without its `xml:` prefix, in profile placement order. Within a placement it orders items by `id`. A member of a surfaced conflict group renders as `<{tag} id="{id}" conflict="{group id}">` instead, with the same body and closing tag. It escapes `&`, `<` and `>` in bodies, and additionally `"` in attribute values. It supports only `xml:` wraps. Per-item `tokens` count the rendered body; wrapper tokens appear only in `result.input_tokens`.

Implementations vendor these cases pinned by hash, so a case changes only through a reviewed edit here.
