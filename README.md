# cwa-assembler

Reference assembler for the [Context Window Architecture](https://contextwindowarchitecture.io) v2 draft. It turns a frozen snapshot of candidate items into a rendered payload and a trace, without calling a model or reading anything outside the snapshot.

**Status: M0 walking skeleton, not released.** It places, renders, counts, hashes and traces, and reproduces the published fixture byte for byte. Admission, budget fitting and conflict resolution are not implemented; snapshots that need them raise `NotImplementedError` instead of producing a payload the spec would not allow. See [docs/DESIGN.md](docs/DESIGN.md) for the design and milestones.

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
