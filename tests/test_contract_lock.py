"""Vendored contract files match contract.lock.json, and nothing unlisted hides beside them."""
import hashlib

from conftest import ROOT, read_json


def test_vendored_files_match_the_lock():
    lock = read_json(ROOT / "contract.lock.json")["files"]
    for path, expected in lock.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    on_disk = {str(p.relative_to(ROOT)) for base in ("src/cwa/contract/data", "conformance") for p in (ROOT / base).rglob("*") if p.is_file()}
    assert on_disk == set(lock)
