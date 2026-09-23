"""What the installed package ships beyond its code."""
from __future__ import annotations

from importlib.resources import files


def test_the_package_declares_its_inline_types():
    """PEP 561: type checkers use cwa's annotations only when the package ships a py.typed marker."""
    assert files("cwa").joinpath("py.typed").is_file()


def test_the_package_type_checks():
    """py.typed promises usable annotations, so every commit keeps mypy clean over src/cwa."""
    from mypy import api

    from conftest import ROOT

    report, errors, status = api.run([str(ROOT / "src" / "cwa")])
    assert status == 0, report + errors
