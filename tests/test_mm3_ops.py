"""MM-3 tests: MCP-style ops surface — ``quarantine <id>`` marks an
existing entry; retain screens secret shapes into quarantine."""

from __future__ import annotations

import json

import pytest

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

from fixtures import (
    CLEAN_FACT,
    FAKE_PEM,
    LONG_BASE64_FACT,
    PEM_FACT,
    SECRET_FACT,
)


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# retain: secret shapes land in quarantine, not active
# ---------------------------------------------------------------------------


def test_retain_token_like_string_quarantines(store):
    e = ops.retain(store, SECRET_FACT)  # AWS-shaped access key id
    assert e.status == "quarantined"
    assert any(r.startswith("secret:") for r in e.quarantine_reasons)


def test_retain_private_key_marker_quarantines(store):
    e = ops.retain(store, PEM_FACT)
    assert e.status == "quarantined"
    assert "secret:pem_private_key" in e.quarantine_reasons
    assert FAKE_PEM.splitlines()[1] in e.content  # stored, not printed


def test_retain_long_high_entropy_run_quarantines(store):
    e = ops.retain(store, LONG_BASE64_FACT)
    assert e.status == "quarantined"
    assert "shape:long_base64_run" in e.quarantine_reasons


def test_retain_pairing_code_quarantines(store):
    # assembled — repo convention keeps secret-shaped literals out of files
    code = "ABCD" + "-" + "EFGH" + "-" + "IJKL"
    e = ops.retain(store, f"pairing code: {code} for the box")
    assert e.status == "quarantined"
    assert "secret:devin_pairing_code" in e.quarantine_reasons


# ---------------------------------------------------------------------------
# quarantine <id>: mark an existing entry
# ---------------------------------------------------------------------------


def test_quarantine_marks_active_entry(store):
    e = ops.retain(store, CLEAN_FACT)
    out = ops.quarantine_entry(store, e.id)
    assert out.status == "quarantined"
    assert "manual:user" in out.quarantine_reasons
    # quarantined never surfaces in recall
    assert ops.recall(store, "") == []


def test_quarantine_marks_proposed_entry(store):
    e = store.insert("a draft", status="proposed")
    out = ops.quarantine_entry(store, e.id, reason="manual:spam")
    assert out.status == "quarantined"
    assert "manual:spam" in out.quarantine_reasons


def test_quarantine_existing_reasons_preserved(store):
    e = ops.retain(store, SECRET_FACT)
    out = ops.quarantine_entry(store, e.id, reason="manual:double-check")
    assert any(r.startswith("secret:") for r in out.quarantine_reasons)
    assert "manual:double-check" in out.quarantine_reasons


def test_quarantine_retracted_raises(store):
    e = ops.retain(store, CLEAN_FACT)
    ops.retract(store, e.id)
    with pytest.raises(ops.InvalidTransitionError):
        ops.quarantine_entry(store, e.id)


def test_quarantine_missing_entry_raises(store):
    with pytest.raises(ops.EntryNotFoundError):
        ops.quarantine_entry(store, 999)


def test_release_after_manual_quarantine(store):
    e = ops.retain(store, CLEAN_FACT)
    ops.quarantine_entry(store, e.id)
    out = ops.release(store, e.id)
    assert out.status == "active"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_quarantine_marks_entry(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT, "--json"])
    entry = json.loads(capsys.readouterr().out)

    assert (
        main(["--db", db, "quarantine", str(entry["id"]),
              "--reason", "manual:typo"])
        == 0
    )
    out = capsys.readouterr().out
    assert "status=quarantined" in out

    assert main(["--db", db, "quarantine", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == [entry["id"]]
    assert "manual:typo" in rows[0]["quarantine_reasons"]


def test_cli_retain_secret_never_prints_secret(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    assert (
        main(["--db", db, "retain", PEM_FACT])
        == 0
    )
    out = capsys.readouterr().out
    assert "status=quarantined" in out
    # text output prints reasons/ids — not the stored secret blob
    assert "ZmFrZS1ibG9i" not in out
