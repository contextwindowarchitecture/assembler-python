"""Rejection (R-17): a snapshot that fails its schemas or a snapshot check is rejected before assembly, with no
payload and no trace. Each vendored rejection case breaks exactly one check (conformance/README.md, Snapshot checks)."""
from __future__ import annotations

import pytest

from cwa import Snapshot, SnapshotError
from conftest import REJECTIONS, read_json


@pytest.mark.parametrize("case", sorted(p.name for p in REJECTIONS.iterdir()))
def test_each_rejection_case_is_rejected_before_assembly(case):
    with pytest.raises(SnapshotError):
        Snapshot.from_json(read_json(REJECTIONS / case / "snapshot.json"))
