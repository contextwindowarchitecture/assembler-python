# AGENTS.md

Instructions for coding agents and contributors working in `cwa-assembler`, the Python reference assembler for the CWA v2 draft. Read [docs/DESIGN.md](docs/DESIGN.md) before changing behavior. It holds the design, the milestone plan (§8) and the decisions already made (§9).

## Commands

```sh
uv sync                                                          # install
uv run pytest                                                    # full suite; must pass before every commit
uv run pytest tests/test_x.py::test_name                         # one test
python scripts/vendor_contract.py --website ../website           # re-vendor the contract after a website change
python scripts/vendor_contract.py --website ../website --check   # fail on drift
```

## Test-driven development

All behavior changes follow red → green → refactor:

1. **Red.** Write the smallest test that states the next piece of required behavior. Name it after the behavior, not the function. Cite the requirement it serves (`R-n`) in the test or its module docstring. Run it and confirm it fails *for the expected reason*. A test that passes before the change, or fails on an import error, proves nothing.
2. **Green.** Write the least code that makes it pass. Run the full suite.
3. **Refactor.** Clean up with the suite green. Change no behavior.

Rules:

- No production code without a failing test that demanded it. Bug fixes start with a test that reproduces the bug.
- Conformance cases (`conformance/cases/`) come from the website repo. When a milestone needs a new spec-level case, add it there first (with its own website tests), re-vendor, and let it fail here before implementing.
- While its milestone is in progress, a vendored case that cannot pass yet goes in `PENDING` in `tests/test_conformance.py`. That marks it as a strict expected failure, so the suite stays green and fails as soon as the case starts passing. Remove it from `PENDING` in the commit that makes it pass.
- Before claiming a test protects something, break the code on purpose and watch the test fail. Restore the code afterwards.
- A conformance-matrix row moves to *implemented* only when tests cover every assembler-scoped clause of that requirement (`contract/assembler-scope.json` in the website repo).

## Commits

- **Commit incrementally**, without being asked, at each green step: one behavior, or one refactor, per commit. Every commit must pass the full suite, so history stays bisectable. Don't commit a red test on its own; the test and the code that satisfies it go together.
- **Never push.** The remote is `origin` (https://github.com/contextwindowarchitecture/assembler), but agents don't push, open pull requests, or fetch-and-rebase. The maintainer publishes commits.
- **Use [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):** `type(scope): summary` in the imperative mood, lower case, no trailing period, at most 72 characters.
  - Types: `feat`, `fix`, `test`, `refactor`, `perf`, `docs`, `build`, `chore`, `ci`.
  - Scopes: `admission`, `defaults`, `conflicts`, `fitting`, `render`, `tokenize`, `snapshot`, `trace`, `canonical`, `contract`, `conformance`, `design`.
  - The body says *why*, and lists the requirement IDs affected.
  - Breaking changes use `!` after the scope and a `BREAKING CHANGE:` footer.
  - A `test:` commit is only for tests that add coverage to existing, already-passing behavior.
- **Sign off every commit:** `git commit -s`. The local commit-msg hook rejects commits without a matching `Signed-off-by`, and it removes `Co-Authored-By` trailers. Don't add or restore them.
- Stage paths explicitly. Never commit `.venv/`, caches, or anything under `.claude/`.

## Architecture rules

- **`assemble()` is pure.** No network, filesystem, clock, randomness in the payload, environment reads, or model calls. Everything that can change the payload arrives in the `Snapshot` (R-18, R-23). `tests/test_purity.py` enforces this; extend it when a new module could reach outside.
- **Validate at the boundary, once.** `Snapshot.from_json` validates against the published schemas. Code after it trusts the model types and does not re-validate.
- **Determinism.** Order anything that reaches the payload or trace by explicit keys. Never iterate a `set` into output. Compare timestamps at full precision (R-2).
- **Don't guess.** If a snapshot needs behavior from a later milestone, raise `NotImplementedError` naming that milestone. Never emit a payload the spec would not allow.
- **Reason codes come from the registry.** Exclusions and refusals use codes in `contract/data/reasons.json` (R-21). A new condition needs a new code in the website repo first.

## The contract is vendored, not edited

`src/cwa/contract/data/` and `conformance/` are copies of the website repo's `schema/`, `contract/` and `conformance/`, pinned by SHA-256 in `contract.lock.json`. `tests/test_contract_lock.py` fails if they are edited here. To change the spec:

1. Change the website repo and run its `npm test`.
2. Commit there.
3. Re-vendor here and commit the lock update: `build(contract): vendor website <short-sha>`.

Re-vendor only from a committed website state. The lock records `"dirty": true` otherwise.
