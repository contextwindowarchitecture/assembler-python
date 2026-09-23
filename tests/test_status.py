"""status.json may only claim what its scope allows and what existing tests exercise."""
import ast

from cwa import contract
from conftest import ROOT, read_json

STATUS = read_json(ROOT / "status.json")["requirements"]
SCOPE = {row["id"]: row["scope"] for row in contract.load("assembler-scope.json")}
ALLOWED = {
    "assembler": {"planned", "in progress", "implemented"},
    "boundary": {"planned", "in progress", "boundary-checked"},
    "application": {"documented"},
}


def test_every_requirement_has_one_status_in_order():
    assert [row["id"] for row in STATUS] == [f"R-{n}" for n in range(1, 24)]


def test_each_status_fits_its_scope():
    for row in STATUS:
        assert row["status"] in ALLOWED[SCOPE[row["id"]]], row["id"]


def test_claims_cite_tests_that_exist():
    defined: dict[str, set[str]] = {}
    for row in STATUS:
        if row["status"] in ("implemented", "boundary-checked"):
            assert row["evidence"], f"{row['id']} claims {row['status']} without evidence"
        for node in row["evidence"]:
            path, name = node.split("::")
            if path not in defined:
                tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
                defined[path] = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            assert name in defined[path], f"{row['id']} cites missing test {node}"
