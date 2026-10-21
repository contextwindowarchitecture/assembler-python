# Contributing to assembler-python

This is the reference assembler for the [Context Window Architecture](https://contextwindowarchitecture.io) draft. The specification lives in its own repository, [contextwindowarchitecture/contextwindowarchitecture](https://github.com/contextwindowarchitecture/contextwindowarchitecture). If a change alters what an assembler must do, it starts there, and this repository follows.

[AGENTS.md](AGENTS.md) holds the full rules. Coding agents and people follow the same ones. This page is the short version.

## Set up

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv sync          # install, with the dev tools (pytest, hypothesis, mypy)
uv run pytest    # the full suite, mypy over src/cwa included; it must pass before every commit
```

## How changes are made

**Test first.** Every behavior change starts with a test that fails for the right reason. Next comes the least code that makes it pass, then cleanup with the suite green. A bug fix starts with a test that reproduces the bug. Name tests after the behavior, and cite the requirement (`R-n`) they serve.

**`assemble()` stays pure.** It never touches the network, the filesystem, the environment or a model, and the clock and randomness never reach the payload. Anything that can change the payload arrives in the snapshot. `tests/test_purity.py` enforces this.

**Documentation moves with the code.** A commit that changes behavior also updates the docstring of the API it changes, `docs/DESIGN.md`, the claims in `status.json`, and the README section a caller would read. The README is written for application developers. Keep its Status section to a few sentences.

## Commits

- One behavior, or one refactor, per commit, and every commit passes the full suite. When you pipe pytest's output, run `set -o pipefail` first, or a failing run looks green.
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): summary`, lower case, imperative, at most 72 characters. The body says why and lists the requirement IDs affected. AGENTS.md lists the types and scopes.
- Sign off every commit (`git commit -s`).
- Never create or edit a changelog file. The release workflow ([.github/workflows/release.yml](.github/workflows/release.yml)) writes each tag's release notes from the commit subjects with [git-cliff](https://git-cliff.org) (`cliff.toml`), so a commit's subject line is its changelog entry.

## Conformance

The conformance cases come from the specification repository. Each one is a snapshot in, and the exact payload and trace out. The rejection cases are snapshots that must be refused before assembly.

```sh
uv run python -m cwa.conformance > conformance-report.json   # regenerate the committed report
```

Regenerate the report whenever a case or the code changes. `tests/test_report.py` fails while it is stale. The runner follows the specification's rules for components an implementation lacks. It skips a case only when every tokenizer or renderer it needs and this assembler lacks is optional. It fails a case that needs a required one. This assembler provides every published tokenizer and renderer, so nothing is skipped today.

`status.json` claims, per requirement, what this assembler implements, and cites the tests behind each claim. `tests/test_status.py` rejects a claim whose tests don't exist, or one made while a case for that requirement fails.

## The contract is vendored

Schemas, slot defaults, reason codes and conformance cases are copied from the specification repository into `src/cwa/contract/data/` and `conformance/`. Each file is pinned by SHA-256 in `contract.lock.json`. Don't edit them here, because `tests/test_contract_lock.py` fails if you do. Change the specification repository, commit there, then re-vendor:

```sh
python scripts/vendor_contract.py                                      # copy from ../contextwindowarchitecture and rewrite the lock
python scripts/vendor_contract.py --check                              # fail on drift
python scripts/vendor_contract.py --spec ../contextwindowarchitecture  # name the checkout explicitly
```

Re-vendor only from a committed state of the specification repository. The lock records the source repository and commit, and the conformance report repeats them.

## Performance

```sh
uv run python scripts/bench.py   # time assemble(); record changes in docs/DESIGN.md §7
```

## CI and releases

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the suite on Python 3.11, 3.12, 3.13 and 3.14. It also checks the vendored contract against the specification commit that `contract.lock.json` pins.

Each tag gets a GitHub release once CI passes on the tagged commit ([.github/workflows/release.yml](.github/workflows/release.yml)). The release notes name the specification repository and commit, then list the tag's own commits, written by git-cliff. A tag that isn't `vX.Y.Z`, such as `draft-release`, is a prerelease. A tag pushed before the workflow existed is released with `gh workflow run release.yml -f tag=<tag>`.
