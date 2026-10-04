"""MM-2 tests: contradiction links on retain, ``conflicts`` listing,
and additive migrations on pre-F4 databases."""

from __future__ import annotations

import json
import sqlite3

import pytest

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, SECRET_FACT


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


ALWAYS_PYTEST = "Always run pytest before pushing."
NEVER_PYTEST = "Never run pytest before pushing."


# ---------------------------------------------------------------------------
# ops-level conflict detection
# ---------------------------------------------------------------------------


def test_conflicting_retain_links_both_kept(store):
    old = ops.retain(store, ALWAYS_PYTEST)
    new = ops.retain(store, NEVER_PYTEST)

    assert new.status == "active"
    assert new.conflicts_with == old.id
    # nothing is overwritten — both stay active
    assert store.get(old.id).status == "active"
    pairs = ops.conflicts(store)
    assert [(n.id, o.id) for n, o in pairs] == [(new.id, old.id)]


def test_same_polarity_is_not_a_conflict(store):
    ops.retain(store, ALWAYS_PYTEST)
    similar = ops.retain(store, "Always run pytest before pushing commits.")
    # different subject key (extra token) OR same polarity — either way no link
    assert similar.conflicts_with is None


def test_different_subject_is_not_a_conflict(store):
    ops.retain(store, ALWAYS_PYTEST)
    other = ops.retain(store, "Never commit secrets to the repository.")
    assert other.conflicts_with is None
    assert ops.conflicts(store) == []


def test_identical_content_is_a_duplicate_not_a_conflict(store):
    ops.retain(store, ALWAYS_PYTEST)
    dup = ops.retain(store, ALWAYS_PYTEST)
    assert dup.conflicts_with is None


def test_quarantined_retain_does_not_conflict_scan(store):
    ops.retain(store, ALWAYS_PYTEST)
    suspect = ops.retain(store, SECRET_FACT)
    assert suspect.status == "quarantined"
    assert suspect.conflicts_with is None


def test_conflicts_against_retracted_history_ignored(store):
    old = ops.retain(store, ALWAYS_PYTEST)
    ops.retract(store, old.id)
    new = ops.retain(store, NEVER_PYTEST)
    assert new.conflicts_with is None


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_retain_reports_conflict(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", ALWAYS_PYTEST, "--json"])
    old = json.loads(capsys.readouterr().out)

    assert main(["--db", db, "retain", NEVER_PYTEST]) == 0
    out = capsys.readouterr().out
    assert f"conflicts={old['id']}" in out


def test_cli_conflicts_lists_pairs(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", ALWAYS_PYTEST])
    main(["--db", db, "retain", NEVER_PYTEST])
    capsys.readouterr()

    assert main(["--db", db, "conflicts"]) == 0
    out = capsys.readouterr().out
    assert "pytest" in out

    assert main(["--db", db, "conflicts", "--json"]) == 0
    pairs = json.loads(capsys.readouterr().out)
    assert len(pairs) == 1
    assert pairs[0]["newer"]["content"] == NEVER_PYTEST
    assert pairs[0]["older"]["content"] == ALWAYS_PYTEST


def test_cli_conflicts_empty(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert main(["--db", db, "conflicts"]) == 0
    assert "no conflicts" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# migration: a pre-F4 memory.db upgrades in place
# ---------------------------------------------------------------------------

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


def _make_old_db(path):
    """A memory.db as written before F4: 3-status CHECK, no new columns."""
    con = sqlite3.connect(path)
    with con:
        con.execute(_OLD_DDL)
        con.execute(
            "INSERT INTO entries(content, tags, created_at, status, version)"
            " VALUES ('old fact', '[]', 1700000000000, 'active', 1)"
        )
        con.execute(
            "INSERT INTO entries(content, tags, created_at, status, version,"
            " supersedes_id) VALUES ('newer fact', '[]', 1700000000001,"
            " 'retracted', 2, 1)"
        )
    con.close()


def test_old_db_migrates_and_keeps_rows(tmp_path):
    db = tmp_path / "memory.db"
    _make_old_db(db)
    with MemoryStore(db) as store:
        rows = store.entries()
        assert len(rows) == 2
        assert rows[0].content == "newer fact"  # newest first
        old = store.get(1)
        assert old.status == "active"
        # new columns exist and default sensibly
        assert old.conflicts_with is None
        assert old.workspace is None
        # supersedes chain survived the rebuild
        assert store.get(2).supersedes_id == 1


def test_old_db_accepts_proposed_after_migration(tmp_path):
    db = tmp_path / "memory.db"
    _make_old_db(db)
    with MemoryStore(db) as store:
        e = store.insert("a proposed fact", status="proposed")
        assert e.status == "proposed"
        e2 = ops.approve(store, e.id)
        assert e2.status == "active"


def test_old_db_conflict_linking_works(tmp_path):
    db = tmp_path / "memory.db"
    _make_old_db(db)
    with MemoryStore(db) as store:
        ops.retain(store, ALWAYS_PYTEST)
        new = ops.retain(store, NEVER_PYTEST)
        assert new.conflicts_with is not None
