"""assemble() reads nothing outside the snapshot: no network, clock, files, environment or
randomness (R-18, R-23)."""
import ast
import builtins
import datetime
import io
import itertools
import os
import random
import socket
import time
from collections.abc import Mapping
from contextlib import contextmanager

import pytest

from cwa import Snapshot, assemble, contract
from conftest import CASES, ROOT, read_json
from test_conformance import GAPS, PENDING


def _forbidden(*args, **kwargs):
    raise AssertionError("assemble() reached outside its snapshot")


class _NoClock(datetime.datetime):
    now = utcnow = today = classmethod(_forbidden)


class _NoEnvironment(Mapping):
    def __getitem__(self, key):
        _forbidden()

    def __iter__(self):
        _forbidden()

    def __len__(self):
        _forbidden()


@contextmanager
def _sealed(monkeypatch):
    """Every way out of the snapshot raises, for the duration of the block only (pytest itself
    reads the environment between test phases)."""
    with monkeypatch.context() as m:
        m.setattr(socket, "socket", _forbidden)
        m.setattr(socket, "create_connection", _forbidden)
        for name in ("time", "time_ns", "monotonic", "perf_counter", "localtime", "gmtime"):
            m.setattr(time, name, _forbidden)
        m.setattr(datetime, "datetime", _NoClock)
        for module, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "urandom")):
            m.setattr(module, name, _forbidden)
        m.setattr(os, "environ", _NoEnvironment())
        for name in ("random", "randint", "randrange", "choice", "choices", "shuffle", "sample", "uniform", "getrandbits"):
            m.setattr(random, name, _forbidden)
        yield


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir()))
def test_assemble_needs_no_network_or_clock(case, monkeypatch):
    contract.validator.cache_clear()  # as in a fresh process: nothing loaded yet but what the snapshot needed
    try:
        snapshot = Snapshot.from_json(read_json(CASES / case / "snapshot.json"))
    except GAPS:
        if case not in PENDING:
            raise
        return  # a pending case whose renderer or tokenizer does not exist yet
    with _sealed(monkeypatch):
        if case not in PENDING:
            assemble(snapshot, trace_id="t")
            assemble(snapshot, trace_id="t", clock=itertools.count().__next__)  # a lent clock is the only one read (D-9)
            return
        try:
            assemble(snapshot, trace_id="t")
        except GAPS:
            pass  # a pending case's milestone gap, not a read outside the snapshot


# Modules that reach a network, a model, a clock, randomness, processes or the environment. uuid
# stays allowed: it makes only the default trace_id, which R-23 lets differ.
FORBIDDEN_MODULES = {"aiohttp", "anthropic", "asyncio", "ftplib", "google", "http", "httpx", "multiprocessing", "openai",
                     "random", "requests", "secrets", "smtplib", "socket", "ssl", "subprocess", "threading", "tiktoken",
                     "time", "urllib", "websockets"}
FORBIDDEN_CALLS = {"now", "utcnow", "today", "getenv", "environ", "urandom", "system", "popen"}


def test_the_core_imports_nothing_that_reaches_outside():
    """A static backstop for the runtime guards above: it also covers code no case happens to reach."""
    found = []
    for path in sorted((ROOT / "src" / "cwa").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            found += [f"{path.name}: import {n}" for n in names if n.split(".")[0] in FORBIDDEN_MODULES]
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
                found.append(f"{path.name}:{node.lineno}: .{node.attr}")
    assert found == []
