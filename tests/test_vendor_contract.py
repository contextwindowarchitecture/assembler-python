"""scripts/vendor_contract.py vendors only the files the website's git tracks.

A website checkout holds untracked and ignored files too, such as the __pycache__ that running its own Python tests
leaves under conformance/. Vendoring those would pin a local build artifact in contract.lock.json, and a fresh clone,
which never has it, would fail tests/test_contract_lock.py.
"""
import importlib.util
import subprocess

from conftest import ROOT

spec = importlib.util.spec_from_file_location("vendor_contract", ROOT / "scripts" / "vendor_contract.py")
vendor_contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor_contract)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_untracked_and_ignored_website_files_are_not_vendored(tmp_path):
    website = tmp_path / "website"
    (website / "conformance" / "tests" / "__pycache__").mkdir(parents=True)
    (website / "schema").mkdir()
    (website / ".gitignore").write_text("__pycache__/\n")
    (website / "conformance" / "check.py").write_text("")
    (website / "conformance" / "tests" / "test_x.py").write_text("")
    (website / "schema" / "a.schema.json").write_text("{}")
    git(website, "init", "-q")
    git(website, "add", ".")
    (website / "conformance" / "tests" / "__pycache__" / "test_x.cpython-314.pyc").write_bytes(b"\0")
    (website / "conformance" / "scratch.txt").write_text("untracked")
    (website / "schema" / "b.schema.json").write_text("{}")

    vendored = {str(dest.relative_to(ROOT)) for dest in vendor_contract.sources(website)}

    assert {"conformance/check.py", "conformance/tests/test_x.py", "src/cwa/contract/data/schema/a.schema.json"} <= vendored
    assert not {"conformance/tests/__pycache__/test_x.cpython-314.pyc", "conformance/scratch.txt",
                "src/cwa/contract/data/schema/b.schema.json"} & vendored
