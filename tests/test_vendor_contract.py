"""scripts/vendor_contract.py vendors only the files the specification repository's git tracks, and names that repository.

A spec checkout holds untracked and ignored files too, such as the __pycache__ that running its own Python tests
leaves under conformance/. Vendoring those would pin a local build artifact in contract.lock.json, and a fresh clone,
which never has it, would fail tests/test_contract_lock.py.
"""
import importlib.util
import subprocess

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location("vendor_contract", ROOT / "scripts" / "vendor_contract.py")
vendor_contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor_contract)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def commit(cwd, *args):
    """A throwaway commit in a temporary checkout, clear of the user's hooks and signing."""
    git(cwd, "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t",
        "commit", "-q", "-m", "x", *args)


def test_untracked_and_ignored_spec_files_are_not_vendored(tmp_path):
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


@pytest.mark.parametrize("url", [
    "git@github.com:contextwindowarchitecture/contextwindowarchitecture.git",
    "git@github.com:contextwindowarchitecture/contextwindowarchitecture",
    "https://github.com/contextwindowarchitecture/contextwindowarchitecture.git",
    "ssh://git@github.com/contextwindowarchitecture/contextwindowarchitecture",
])
def test_the_lock_names_the_repository_the_checkout_comes_from(tmp_path, url):
    """The specification repository is the contract's source now, so the lock reads the source from the checkout's
    origin rather than naming one repository whatever was vendored."""
    spec = tmp_path / "spec"
    (spec / "conformance").mkdir(parents=True)
    (spec / "conformance" / "README.md").write_text("")
    git(spec, "init", "-q")
    git(spec, "add", ".")
    commit(spec)
    git(spec, "remote", "add", "origin", url)

    assert vendor_contract.git_state(spec)["repository"] == "contextwindowarchitecture/contextwindowarchitecture"


def test_a_checkout_without_a_github_origin_is_refused(tmp_path):
    """Guessing the repository would put a wrong source in the lock, and from there in the conformance report."""
    spec = tmp_path / "spec"
    spec.mkdir()
    git(spec, "init", "-q")
    commit(spec, "--allow-empty")
    git(spec, "remote", "add", "origin", "https://example.com/spec.git")

    with pytest.raises(SystemExit, match="origin"):
        vendor_contract.git_state(spec)


def test_the_specification_checkout_is_the_source():
    """The contract is vendored from the specification repository's checkout beside this one, not from the website."""
    assert vendor_contract.parse_args([]).spec == ROOT.parent / "contextwindowarchitecture"
    assert vendor_contract.parse_args(["--spec", "x", "--check"]).spec.name == "x"
    with pytest.raises(SystemExit):
        vendor_contract.parse_args(["--website", "../website"])
