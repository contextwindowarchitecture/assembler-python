"""Rejection (R-17): a snapshot that fails its schemas or a snapshot check is rejected before assembly, with no
payload and no trace. Each vendored rejection case breaks exactly one check (conformance/README.md, Snapshot checks)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, SnapshotError, UnsupportedComponentError
from cwa.render import REQUIRED
from conftest import REJECTIONS, read_json


@pytest.mark.parametrize("case", sorted(p.name for p in REJECTIONS.iterdir()))
def test_each_rejection_case_is_rejected_before_assembly(case):
    """A case that breaks the check of an optional renderer this assembler lacks cannot run that check, so it is
    skipped, as conformance/README.md's Reporting results reports it. Every other check runs without a renderer."""
    with pytest.raises(SnapshotError):
        try:
            Snapshot.from_json(read_json(REJECTIONS / case / "snapshot.json"))
        except UnsupportedComponentError as error:
            if error.component == "renderer" and error.id not in REQUIRED:
                pytest.skip(f"no renderer {error.id}")
            raise
