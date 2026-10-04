"""Offline-core guard: the core must not open sockets.

Release checklist item: "no-network core test (CI): fails if the core
opens a socket". An autouse fixture monkeypatches ``socket.socket.connect``,
``socket.socket.connect_ex`` and ``socket.create_connection`` to raise
``OfflineCoreError`` for the duration of every test in this file, then the
tests run the repo's core operations end to end. This is a guard, not a
mock: any in-process network access fails the suite.

Intentional online paths are excluded by design: none exist in the core —
retain/recall/prime/extract operate on a local SQLite memory.db. Only
in-process sockets are blocked here.

Opt-out: mark a test ``@pytest.mark.network`` to run it without the socket
block (reserved for tests that intentionally exercise the network).

Run with:
``PYTHONPATH=src:../devin-internals-spec/src python -m pytest tests/test_offline_core.py``
(conftest imports ``devin_internals`` from the sibling checkout).
"""

from __future__ import annotations

import json
import socket

import pytest

from devin_memory.cli import main

from fixtures import CLEAN_FACT, CLEAN_FACT_2


class OfflineCoreError(RuntimeError):
    """Raised when core code tries to open a network connection."""


def _offline_fail(*args, **kwargs):
    raise OfflineCoreError("core opened a socket during the offline-core test")


@pytest.fixture(autouse=True)
def _block_sockets(request, monkeypatch):
    """Block all outbound sockets; opt out with ``@pytest.mark.network``."""
    if request.node.get_closest_marker("network"):
        return
    monkeypatch.setattr(socket.socket, "connect", _offline_fail)
    monkeypatch.setattr(socket.socket, "connect_ex", _offline_fail)
    monkeypatch.setattr(socket, "create_connection", _offline_fail)


def test_socket_block_is_active():
    """Sanity check: the guard itself raises on any connect attempt."""
    with pytest.raises(OfflineCoreError):
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)
    with pytest.raises(OfflineCoreError):
        socket.socket().connect(("127.0.0.1", 1))


def test_retain_recall_prime_offline(tmp_path, capsys):
    """retain → recall → prime on a temp memory store — all offline."""
    db = str(tmp_path / "memory.db")

    assert main(["--db", db, "retain", CLEAN_FACT, "--tags", "a,b"]) == 0
    assert main(["--db", db, "retain", CLEAN_FACT_2]) == 0
    capsys.readouterr()

    assert main(["--db", db, "recall", "sessions", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["content"] == CLEAN_FACT for r in rows)

    assert main(["--db", db, "prime"]) == 0
    primed = capsys.readouterr().out
    assert CLEAN_FACT in primed and CLEAN_FACT_2 in primed
