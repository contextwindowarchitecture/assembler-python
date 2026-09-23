"""Copy the CWA contract and conformance cases from the website repo, pinned by SHA-256.

    python scripts/vendor_contract.py --website ../website          # vendor and rewrite contract.lock.json
    python scripts/vendor_contract.py --website ../website --check  # fail if vendored files drift from the website
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "cwa" / "contract" / "data"
CONFORMANCE = ROOT / "conformance"
LOCK = ROOT / "contract.lock.json"
CONTRACT_FILES = ("slot-defaults.json", "reasons.json", "requirements.json", "assembler-scope.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(website: Path) -> dict[Path, Path]:
    """Map each vendored destination to its website source."""
    mapping = {DATA / "schema" / p.name: p for p in sorted((website / "schema").glob("*.schema.json"))}
    mapping |= {DATA / name: website / "contract" / name for name in CONTRACT_FILES}
    for p in sorted((website / "conformance").rglob("*")):
        if p.is_file():
            mapping[CONFORMANCE / p.relative_to(website / "conformance")] = p
    return mapping


def git_state(website: Path) -> dict:
    run = lambda *args: subprocess.run(["git", "-C", str(website), *args], capture_output=True, text=True, check=True).stdout.strip()
    tracked = ["schema", "contract", "conformance"]
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", *tracked))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mapping = sources(args.website.resolve())

    if args.check:
        drift = [str(dest.relative_to(ROOT)) for dest, src in mapping.items() if not dest.exists() or sha256(dest) != sha256(src)]
        lock = json.loads(LOCK.read_text())
        extra = sorted(set(lock["files"]) - {str(d.relative_to(ROOT)) for d in mapping})
        for path in drift + extra:
            print(f"drift: {path}", file=sys.stderr)
        return 1 if drift or extra else 0

    for directory in (DATA, CONFORMANCE):
        if directory.exists():
            shutil.rmtree(directory)
    for dest, src in mapping.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    lock = {
        "source": {"repository": "contextwindowarchitecture/website", **git_state(args.website)},
        "files": {str(dest.relative_to(ROOT)): sha256(dest) for dest in sorted(mapping)},
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"Vendored {len(mapping)} files from {lock['source']['commit'][:7]}{' (dirty)' if lock['source']['dirty'] else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
