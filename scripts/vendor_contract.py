"""Copy the CWA contract and conformance cases from the specification repository, pinned by SHA-256.

    python scripts/vendor_contract.py                                        # vendor ../contextwindowarchitecture
    python scripts/vendor_contract.py --check                                # fail if vendored files drift from it
    python scripts/vendor_contract.py --spec ../contextwindowarchitecture    # name the checkout explicitly
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "cwa" / "contract" / "data"
CONFORMANCE = ROOT / "conformance"
LOCK = ROOT / "contract.lock.json"
CONTRACT_FILES = ("slot-defaults.json", "reasons.json", "requirements.json", "assembler-scope.json")
SPEC = ROOT.parent / "contextwindowarchitecture"
GITHUB = re.compile(r"github\.com[:/](?P<repository>[^/]+/[^/]+?)(?:\.git)?/?$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked(website: Path) -> set[Path]:
    """The files the spec checkout's git tracks: its untracked and ignored files (__pycache__) are not the contract."""
    out = subprocess.run(["git", "-C", str(website), "ls-files", "-z", "--", "schema", "contract", "conformance"],
                         capture_output=True, text=True, check=True).stdout
    return {website / name for name in out.split("\0") if name}


def sources(website: Path) -> dict[Path, Path]:
    """Map each vendored destination to its source in the spec checkout."""
    files = tracked(website)
    mapping = {DATA / "schema" / p.name: p for p in sorted((website / "schema").glob("*.schema.json")) if p in files}
    mapping |= {DATA / name: website / "contract" / name for name in CONTRACT_FILES}
    for p in sorted((website / "conformance").rglob("*")):
        if p in files:
            mapping[CONFORMANCE / p.relative_to(website / "conformance")] = p
    return mapping


def git_state(website: Path) -> dict:
    run = lambda *args: subprocess.run(["git", "-C", str(website), *args], capture_output=True, text=True, check=True).stdout.strip()
    tracked = ["schema", "contract", "conformance"]
    origin = subprocess.run(["git", "-C", str(website), "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    match = GITHUB.search(origin)
    if not match:
        raise SystemExit(f"{website}: origin {origin or '(none)'} is not a GitHub repository; the lock names its source as owner/name")
    return {"repository": match["repository"], "commit": run("rev-parse", "HEAD"),
            "dirty": bool(run("status", "--porcelain", "--", *tracked))}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=SPEC, help="the specification repository's checkout (default: %(default)s)")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    mapping = sources(args.spec.resolve())

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
        "source": git_state(args.spec),
        "files": {str(dest.relative_to(ROOT)): sha256(dest) for dest in sorted(mapping)},
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"Vendored {len(mapping)} files from {lock['source']['commit'][:7]}{' (dirty)' if lock['source']['dirty'] else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
