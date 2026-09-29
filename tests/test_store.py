"""Store tests: schema creation, inserts, status transitions, ordering."""

from __future__ import annotations

import sqlite3

import pytest

from devin_memory.store import Entry, MemoryStore

from fixtures import CLEAN_FACT


def test_store_creates_db_and_schema(tmp_path):
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    store.close()

    assert db.is_file()
    con = sqlite3.connect(db)
    try:
        cols = {
            r[1] for r in con.execute("PRAGMA table_info(entries)")
        }
        assert {
            "id",
            "content",
            "tags",
            "source_session_id",
            "source_rowid",
            "created_at",
            "status",
            "version",
            "supersedes_id",
            "quarantine_reasons",
        } <= cols
    finally:
        con.close()


def test_store_is_idempotent_on_reopen(tmp_path):
    db = tmp_path / "memory.db"
    with MemoryStore(db) as store:
        store.insert(CLEAN_FACT, tags=["a"])
    with MemoryStore(db) as store:  # reopen — schema must tolerate it
        assert len(store.entries()) == 1


def test_insert_returns_typed_entry(tmp_path):
    with MemoryStore(tmp_path / "m.db") as store:
        e = store.insert(
            CLEAN_FACT,
            tags=["sqlite", "internals"],
            quarantine_reasons=["limit:none"],
            source_session_id="sess-1",
            source_rowid=42,
        )
    assert isinstance(e, Entry)
    assert e.id == 1
    assert e.content == CLEAN_FACT
    assert e.tags == ("sqlite", "internals")
    assert e.status == "active"
    assert e.version == 1
    assert e.supersedes_id is None
    assert e.source_session_id == "sess-1"
    assert e.source_rowid == 42
    assert e.quarantine_reasons == ("limit:none",)
    assert isinstance(e.created_at, int) and e.created_at > 0


def test_get_and_status_transitions(tmp_path):
    with MemoryStore(tmp_path / "m.db") as store:
        e = store.insert(CLEAN_FACT, [], status="active")
        assert store.get(e.id).status == "active"
        store.set_status(e.id, "quarantined")
        assert store.get(e.id).status == "quarantined"
        assert store.get(9999) is None


def test_set_status_rejects_bad_value(tmp_path):
    with MemoryStore(tmp_path / "m.db") as store:
        e = store.insert(CLEAN_FACT, [])
        with pytest.raises(ValueError):
            store.set_status(e.id, "bogus")


def test_entries_filter_and_order(tmp_path):
    with MemoryStore(tmp_path / "m.db") as store:
        a = store.insert("first")
        b = store.insert("second", status="quarantined", quarantine_reasons=["x"])
        c = store.insert("third")

        all_entries = store.entries()
        assert [e.id for e in all_entries] == [c.id, b.id, a.id]  # newest first
        assert [e.id for e in store.entries(status="active")] == [c.id, a.id]
        assert [e.id for e in store.entries(status="quarantined")] == [b.id]
        assert [e.id for e in store.entries(limit=2)] == [c.id, b.id]


def test_counts(tmp_path):
    with MemoryStore(tmp_path / "m.db") as store:
        store.insert("a")
        store.insert("b", status="quarantined", quarantine_reasons=["r"])
        store.insert("c", status="retracted")
        assert store.counts() == {
            "active": 1,
            "quarantined": 1,
            "retracted": 1,
        }
