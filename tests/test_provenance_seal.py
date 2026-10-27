"""Tamper-evident provenance seal: every write stores a sha256 over the
columns frozen at insert time; ``verify`` recomputes and reports
``VERIFIED_SEALED`` / ``UNSEALED`` / ``TAMPER_SUSPECT``.

The seal detects post-hoc edits to sealed columns (content, source ids,
created_at, machine/profile/workspace, chain position). It does not
prove the recorded source was truthful — that is what the optional
``--sessions-db`` audit is for. Legitimate lifecycle transitions
(status, reasons, tags, expires_at) are unsealed on purpose and must
never read as tampering.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import (
    MemoryStore,
    compute_provenance_hash,
    entry_provenance_hash,
)

from fixtures import CLEAN_FACT, SECRET_FACT, make_sessions_db


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _tamper(db_path: Path, entry_id: int, **sets) -> None:
    """Edit a row outside the API — simulates a post-hoc modification."""
    con = sqlite3.connect(db_path)
    cols = ", ".join(f"{k} = ?" for k in sets)
    with con:
        con.execute(
            f"UPDATE entries SET {cols} WHERE id = ?",
            (*sets.values(), entry_id),
        )
    con.close()


# ---------------------------------------------------------------------------
# seal written at insert time, verified on read
# ---------------------------------------------------------------------------


def test_every_write_is_sealed(store):
    e = ops.retain(store, CLEAN_FACT)
    assert e.provenance_hash is not None
    assert len(e.provenance_hash) == 64  # sha256 hexdigest
    assert store.get(e.id).provenance_hash == e.provenance_hash


def test_verify_reports_verified_sealed(store):
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-1")
    report = ops.verify_provenance(store, e.id)
    assert report["seal_status"] == "VERIFIED_SEALED"
    assert report["recomputed_hash"] == e.provenance_hash
    # no sessions.db given — that audit did not run
    assert report["checked"] is False
    assert report["session_found"] is None


def test_entry_seal_recomputes_identically(store):
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-1")
    assert entry_provenance_hash(e) == e.provenance_hash


def test_seal_canonical_form_ignores_mapping_order():
    fields = {
        "content": "fact",
        "source_session_id": "sess-1",
        "source_rowid": 7,
        "created_at": 1700000000000,
        "machine_id": "m-1",
        "profile": "personal",
        "workspace": "/w",
        "conflicts_with": None,
        "version": 2,
        "supersedes_id": 1,
    }
    forward = compute_provenance_hash(fields)
    shuffled = compute_provenance_hash(
        dict(reversed(list(fields.items())))
    )
    assert forward == shuffled
    # any sealed-field change moves the digest
    assert compute_provenance_hash({**fields, "version": 3}) != forward


def test_supersede_seals_the_successor(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    assert new.provenance_hash is not None
    assert new.provenance_hash != old.provenance_hash
    report = ops.verify_provenance(store, new.id)
    assert report["seal_status"] == "VERIFIED_SEALED"


# ---------------------------------------------------------------------------
# tamper detection — sealed columns
# ---------------------------------------------------------------------------


def test_tampered_content_is_suspect(store, tmp_path):
    e = ops.retain(store, CLEAN_FACT)
    _tamper(tmp_path / "memory.db", e.id, content="rewritten fact")
    report = ops.verify_provenance(store, e.id)
    assert report["seal_status"] == "TAMPER_SUSPECT"
    assert report["recomputed_hash"] != e.provenance_hash


def test_tampered_source_session_is_suspect(store, tmp_path):
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-1")
    _tamper(tmp_path / "memory.db", e.id, source_session_id="sess-forged")
    report = ops.verify_provenance(store, e.id)
    assert report["seal_status"] == "TAMPER_SUSPECT"


def test_tampered_created_at_is_suspect(store, tmp_path):
    e = ops.retain(store, CLEAN_FACT)
    _tamper(tmp_path / "memory.db", e.id, created_at=e.created_at + 1)
    report = ops.verify_provenance(store, e.id)
    assert report["seal_status"] == "TAMPER_SUSPECT"


def test_tamper_suspect_even_when_sessions_audit_passes(store, tmp_path):
    """The seal fails loudly — never masked by a green sessions.db half."""
    sessions_db, session_id, _ = make_sessions_db(tmp_path)
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-1")
    # attacker rewrites the claim to a session that really exists
    _tamper(
        tmp_path / "memory.db", e.id, source_session_id=session_id
    )
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["session_found"] is True
    assert report["seal_status"] == "TAMPER_SUSPECT"


# ---------------------------------------------------------------------------
# unsealed columns — lifecycle changes must not read as tampering
# ---------------------------------------------------------------------------


def test_lifecycle_transitions_keep_the_seal(store, tmp_path):
    db = tmp_path / "memory.db"
    e = ops.retain(store, CLEAN_FACT)
    ops.quarantine_entry(store, e.id, reason="manual:review")
    store.set_tags(e.id, ["merged"])
    store.set_expires_at(e.id, "2099-01-01T00:00:00Z")
    _tamper(db, e.id, status="retracted")  # even a hand-edited status
    report = ops.verify_provenance(store, e.id)
    assert report["seal_status"] == "VERIFIED_SEALED"


def test_released_supersession_parent_still_verifies(store):
    """The superseded memory stays verifiable — a held→applied chain
    breaks neither row's seal."""
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)  # held
    ops.release(store, new.id)
    assert ops.verify_provenance(store, old.id)["seal_status"] == (
        "VERIFIED_SEALED"
    )
    assert ops.verify_provenance(store, new.id)["seal_status"] == (
        "VERIFIED_SEALED"
    )


# ---------------------------------------------------------------------------
# unsealed rows — honest state, never silently upgraded
# ---------------------------------------------------------------------------


def test_unsealed_row_reports_unsealed(store, tmp_path):
    e = ops.retain(store, CLEAN_FACT)
    _tamper(tmp_path / "memory.db", e.id, provenance_hash=None)
    report = ops.verify_provenance(store, e.id)
    # dropping the seal cannot fake a VERIFIED result — it just marks
    # the row as what it is: unsealed legacy data
    assert report["seal_status"] == "UNSEALED"
    assert report["recomputed_hash"] is None


_OLD_DDL = """
CREATE TABLE entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  source_session_id TEXT,
  source_rowid INTEGER,
  created_at INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'quarantined', 'retracted')),
  version INTEGER NOT NULL DEFAULT 1,
  supersedes_id INTEGER REFERENCES entries(id),
  quarantine_reasons TEXT NOT NULL DEFAULT '[]',
  machine_id TEXT,
  profile TEXT
);
"""


def test_pre_seal_db_migrates_and_stays_honest(tmp_path):
    """A ≤0.3.1 memory.db upgrades in place: old rows verify UNSEALED,
    new writes are sealed."""
    db = tmp_path / "memory.db"
    con = sqlite3.connect(db)
    with con:
        con.executescript(_OLD_DDL)
        con.execute(
            "INSERT INTO entries(content, tags, created_at, status,"
            " version) VALUES ('legacy fact', '[]', 1700000000000,"
            " 'active', 1)"
        )
    con.close()
    with MemoryStore(db) as store:
        legacy = store.get(1)
        assert legacy.provenance_hash is None
        report = ops.verify_provenance(store, legacy.id)
        assert report["seal_status"] == "UNSEALED"
        new = ops.retain(store, CLEAN_FACT)
        assert new.provenance_hash is not None


# ---------------------------------------------------------------------------
# sessions.db audit parity + CLI exit codes
# ---------------------------------------------------------------------------


def test_sessionsdb_audit_still_runs_with_seal(store, tmp_path):
    sessions_db, session_id, rowid = make_sessions_db(tmp_path)
    e = ops.retain(
        store, CLEAN_FACT, source_session_id=session_id, source_rowid=rowid
    )
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["checked"] is True
    assert report["session_found"] is True
    assert report["rowid_found"] is True
    assert report["seal_status"] == "VERIFIED_SEALED"


def test_cli_verify_seal_only_passes(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT, "--json"])
    entry = json.loads(capsys.readouterr().out)

    assert main(["--db", db, "verify", str(entry["id"])]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["seal_status"] == "VERIFIED_SEALED"
    assert report["sessions_db"] is None


def test_cli_verify_tamper_exits_1(tmp_path, capsys):
    db = tmp_path / "memory.db"
    main(["--db", str(db), "retain", CLEAN_FACT, "--json"])
    entry = json.loads(capsys.readouterr().out)
    _tamper(db, entry["id"], content="edited after the fact")

    assert main(["--db", str(db), "verify", str(entry["id"])]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["seal_status"] == "TAMPER_SUSPECT"


def test_cli_verify_tamper_fails_sessionsdb_pass(tmp_path, capsys):
    sessions_db, session_id, rowid = make_sessions_db(tmp_path)
    db = tmp_path / "memory.db"
    main(
        [
            "--db", str(db), "retain", CLEAN_FACT,
            "--source-session", session_id,
            "--source-rowid", str(rowid), "--json",
        ]
    )
    entry = json.loads(capsys.readouterr().out)
    # the remembered fact is rewritten post-hoc — provenance still
    # points at a real session row, so only the seal can catch this
    _tamper(db, entry["id"], content="edited after the fact")

    rc = main(
        ["--db", str(db), "verify", str(entry["id"]),
         "--sessions-db", str(sessions_db)]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["session_found"] is True
    assert report["rowid_found"] is True
    assert report["seal_status"] == "TAMPER_SUSPECT"
    assert rc == 1


def test_cli_verify_sessionsdb_no_provenance_fails_as_before(tmp_path, capsys):
    """Parity: --sessions-db given but nothing recorded → exit 1."""
    sessions_db, _, _ = make_sessions_db(tmp_path)
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT, "--json"])
    entry = json.loads(capsys.readouterr().out)

    rc = main(
        ["--db", db, "verify", str(entry["id"]),
         "--sessions-db", str(sessions_db)]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["checked"] is False
    assert report["seal_status"] == "VERIFIED_SEALED"
    assert rc == 1
