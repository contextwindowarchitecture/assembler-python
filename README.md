# cwa-assembler

Reference assembler for the [Context Window Architecture](https://contextwindowarchitecture.io) v2 draft. It turns a frozen snapshot of candidate items into a rendered payload and a trace, without calling a model or reading anything outside the snapshot.

**Status: M3 conflict resolution in progress, not released.** Every candidate is admitted or excluded with exactly one registered reason, following the spec's precedence. Items over their own `token_budget` are reduced, then admitted items are shed in tier order and by the route's fitting policy until the rendered payload fits, and assemblies that would break a requirement are refused with a trace and no payload: a missing required slot, protected content over budget, or too little evidence, with a recovery action. All fourteen budget, admission and refusal conformance cases pass byte for byte, and `conflict-instruction` passes too, and the other four conflict cases are pending. Snapshots whose conflict groups name unknown items, share an item or name an undefined fact are rejected before assembly. Instruction conflict groups are resolved by authority or by peers' `conflict_policy`. Unresolved ones are surfaced (marked in the payload) or refused with `conflict_unresolved`, as the route directs. Fact groups and placement checks are not implemented yet; snapshots that need them raise `NotImplementedError` instead of producing a payload the spec would not allow. [status.json](status.json) lists what is claimed per requirement and the tests behind each claim. See [docs/DESIGN.md](docs/DESIGN.md) for the design and milestones.

## Use

```python
from cwa import Snapshot, assemble

snapshot = Snapshot.from_json(document)   # snapshot.schema.json; validated and copied
result = assemble(snapshot)               # pure: no I/O, clock or model

result.payload    # bytes, or None when refused
result.trace      # dict matching trace.schema.json
snapshot.digest() # SHA-256 of the RFC 8785 form, the replay key
```

## Develop

```sh
uv sync
uv run pytest
```

## The contract is vendored

Schemas, slot defaults, reason codes and conformance cases come from the website repository, which owns the spec. They are copied into `src/cwa/contract/data/` and `conformance/`, and every file is pinned by SHA-256 in `contract.lock.json`. Don't edit them here; change them in the website repo, then:

```sh
python scripts/vendor_contract.py --website ../website          # re-vendor and rewrite the lock
python scripts/vendor_contract.py --website ../website --check  # fail on drift
```
