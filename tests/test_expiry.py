"""Expiry + recall-decay tests.

Synthetic entries in tmp_path stores only — no real memory DBs. Entry
age is backdated with a plain SQL UPDATE on ``created_at``; malformed
``expires_at`` values are planted the same way to exercise the read
path's fail-open rule (writes themselves reject bad values).
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from devin_memory import ops
from devin_memory.store import (
    MemoryStore,
    is_expired,
    parse_expires_at,
)

from fixtures import CLEAN_FACT, CLEAN_FACT_2


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def store(db):
    with MemoryStore(db) as s:
        yield s


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _update(db_path: Path, sql: str, args: tuple) -> None:
    """Raw write straight into the db file — backdating/corruption that
    the public API deliberately doesn't offer."""
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute(sql, args)
    finally:
        con.close()


def _age_days(db_path: Path, entry_id: int, days: float) -> None:
    backdated = int((time.time() - days * 86400) * 1000)
    _update(
        db_path,
        "UPDATE entries SET created_at = ? WHERE id = ?",
        (backdated, entry_id),
    )


# ---------------------------------------------------------------------------
# schema + write path
# ---------------------------------------------------------------------------


def test_retain_stores_expires_at(store):
    stamp = _iso(timedelta(days=7))
    e = ops.retain(store, CLEAN_FACT, expires_at=stamp)
    assert e.expires_at == stamp
    assert store.get(e.id).expires_at == stamp
    assert e.to_dict()["expires_at"] == stamp


def test_retain_without_expires_at_is_none(store):
    e = ops.retain(store, CLEAN_FACT)
    assert e.expires_at is None


@pytest.mark.parametrize("bad", ["not-a-date", "yesterday", "", "  ", 1234])
def test_retain_rejects_malformed_expires_at(store, bad):
    with pytest.raises(ValueError):
        ops.retain(store, CLEAN_FACT, expires_at=bad)


def test_insert_rejects_malformed_expires_at(store):
    with pytest.raises(ValueError):
        store.insert(CLEAN_FACT, expires_at="when it feels like it")


def test_set_expires_at_updates_and_clears(store):
    e = store.insert(CLEAN_FACT)
    stamp = _iso(timedelta(hours=1))
    store.set_expires_at(e.id, stamp)
    assert store.get(e.id).expires_at == stamp
    store.set_expires_at(e.id, None)
    assert store.get(e.id).expires_at is None
    with pytest.raises(ValueError):
        store.set_expires_at(e.id, "garbage")


def test_parse_expires_at_accepts_z_and_naive():
    z = parse_expires_at("2030-01-01T00:00:00Z")
    aware = parse_expires_at("2030-01-01T00:00:00+00:00")
    naive = parse_expires_at("2030-01-01T00:00:00")  # read as UTC
    assert z == aware == naive


def test_supersede_inherits_expires_at(store):
    stamp = _iso(timedelta(days=2))
    old = ops.retain(store, CLEAN_FACT, expires_at=stamp)
    new = ops.supersede(store, old.id, CLEAN_FACT_2)
    assert new.expires_at == stamp  # None = inherit, like workspace


def test_supersede_overrides_expires_at(store):
    old = ops.retain(store, CLEAN_FACT, expires_at=_iso(timedelta(days=2)))
    new_stamp = _iso(timedelta(days=30))
    new = ops.supersede(store, old.id, CLEAN_FACT_2, expires_at=new_stamp)
    assert new.expires_at == new_stamp
    with pytest.raises(ValueError):
        ops.supersede(store, new.id, "v3", expires_at="soon-ish")


# ---------------------------------------------------------------------------
# recall: expiry filtering
# ---------------------------------------------------------------------------


def test_expired_entry_excluded_from_recall(store):
    ops.retain(store, "sqlite stores the facts", expires_at=_iso(timedelta(days=-1)))
    live = ops.retain(store, "sqlite is embedded")
    hits = ops.recall(store, "sqlite")
    assert [e.id for e in hits] == [live.id]


def test_expired_entry_excluded_from_empty_query(store):
    ops.retain(store, "old fact", expires_at=_iso(timedelta(days=-1)))
    live = ops.retain(store, "fresh fact")
    hits = ops.recall(store, "")
    assert [e.id for e in hits] == [live.id]


def test_not_yet_expired_included(store):
    e = ops.retain(store, "temporary lease note", expires_at=_iso(timedelta(days=1)))
    hits = ops.recall(store, "lease")
    assert [x.id for x in hits] == [e.id]


def test_no_expires_at_unchanged(store):
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT_2)
    hits = ops.recall(store, "")
    assert [e.id for e in hits] == [b.id, a.id]
    assert all(e.expires_at is None for e in hits)


def test_include_expired_opt_out(store):
    dead = ops.retain(store, "sqlite old rule", expires_at=_iso(timedelta(days=-1)))
    hits = ops.recall(store, "sqlite", include_expired=True)
    assert [e.id for e in hits] == [dead.id]


def test_expired_still_listed_and_fetched(store):
    e = ops.retain(store, "gone soon", expires_at=_iso(timedelta(days=-1)))
    assert is_expired(store.get(e.id))
    assert [x.id for x in ops.list_entries(store, status="active")] == [e.id]


def test_malformed_stored_expires_at_fails_open(store, db):
    """A corrupt TTL (only reachable via hand-edited rows) must not
    silently drop the memory — it surfaces, raw value visible on list."""
    e = ops.retain(store, "corrupt ttl fact")
    _update(db, "UPDATE entries SET expires_at = ? WHERE id = ?", ("garbage", e.id))
    row = store.get(e.id)
    assert row.expires_at == "garbage"
    assert not is_expired(row)
    assert [x.id for x in ops.recall(store, "corrupt")] == [e.id]


# ---------------------------------------------------------------------------
# recall: recency decay
# ---------------------------------------------------------------------------


def test_decay_fresh_outranks_stale(store, db):
    """Stale entry has the stronger raw keyword score but is 200 days
    old — decayed below the fresh weaker hit."""
    stale = ops.retain(store, "alpha alpha alpha alpha")  # occ 4 -> score 5
    fresh = ops.retain(store, "alpha")  # score 2
    _age_days(db, stale.id, 200)  # ~6.7 half-lives -> factor ~0.01

    hits = ops.recall(store, "alpha")
    assert [e.id for e in hits] == [fresh.id, stale.id]


def test_decay_disabled_restores_pure_score_order(store, db):
    stale = ops.retain(store, "alpha alpha alpha alpha")
    fresh = ops.retain(store, "alpha")
    _age_days(db, stale.id, 200)

    hits = ops.recall(store, "alpha", half_life_days=None)
    assert [e.id for e in hits] == [stale.id, fresh.id]
    hits0 = ops.recall(store, "alpha", half_life_days=0)
    assert [e.id for e in hits0] == [stale.id, fresh.id]


def test_short_half_life_ranks_instead_of_dropping(store, db):
    # a decayed-to-zero weight must rank last, not vanish — eligibility
    # is the raw keyword score, not the weighted one
    old = ops.retain(store, "sqlite notes from long ago")
    _age_days(db, old.id, 14)
    hits = ops.recall(store, "sqlite", half_life_days=0.001)
    assert [e.id for e in hits] == [old.id]


def test_half_life_constant_is_read_at_call_time(store, db, monkeypatch):
    # mutating RECALL_DECAY_HALF_LIFE_DAYS tunes the default later calls
    # use — the constant is not captured as a default-arg snapshot
    stale = ops.retain(store, "alpha alpha alpha alpha")
    fresh = ops.retain(store, "alpha")
    _age_days(db, stale.id, 200)
    assert [e.id for e in ops.recall(store, "alpha")] == [
        fresh.id, stale.id]
    monkeypatch.setattr(ops, "RECALL_DECAY_HALF_LIFE_DAYS", 0)
    assert [e.id for e in ops.recall(store, "alpha")] == [
        stale.id, fresh.id]


def test_decay_preserves_same_age_ordering(store):
    """Entries written at the same time keep pure score ordering —
    the existing rank contract is unchanged for same-age hits."""
    weak = ops.retain(store, "mentions sqlite once")
    tagged = ops.retain(store, "database notes", tags=["sqlite"])
    frequent = ops.retain(store, "sqlite sqlite sqlite internals")
    hits = ops.recall(store, "sqlite")
    assert [e.id for e in hits] == [frequent.id, tagged.id, weak.id]


def test_decay_mild_gap_keeps_stronger_hit_first(store, db):
    """A one-day age gap must not flip a clearly stronger stale hit —
    decay tilts close calls, not dominance."""
    strong = ops.retain(store, "sqlite sqlite sqlite sqlite internals")
    _age_days(db, strong.id, 1)
    weak = ops.retain(store, "sqlite")
    hits = ops.recall(store, "sqlite")
    assert [e.id for e in hits] == [strong.id, weak.id]


def test_prime_excludes_expired(store):
    ops.retain(store, "dead walking fact", expires_at=_iso(timedelta(days=-1)))
    ops.retain(store, "live fact")
    text = ops.prime(store)
    assert "live fact" in text
    assert "dead walking" not in text


# ---------------------------------------------------------------------------
# backward compat: a pre-expires_at memory.db upgrades in place
# ---------------------------------------------------------------------------

_OLD_SCHEMA_DDL = """
CREATE TABLE entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  source_session_id TEXT,
  source_rowid INTEGER,
  created_at INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'proposed', 'quarantined', 'retracted')),
  version INTEGER NOT NULL DEFAULT 1,
  supersedes_id INTEGER REFERENCES entries(id),
  quarantine_reasons TEXT NOT NULL DEFAULT '[]',
  machine_id TEXT,
  profile TEXT,
  conflicts_with INTEGER REFERENCES entries(id),
  workspace TEXT
);
"""


def test_db_without_expires_at_migrates(tmp_path):
    """A store written before the column existed opens unchanged:
    additive ALTER, old rows read as expires_at=None, recall intact."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    with con:
        con.executescript(_OLD_SCHEMA_DDL)
        con.execute(
            "INSERT INTO entries(content, created_at) VALUES (?, ?)",
            ("legacy fact about sqlite", 1_700_000_000_000),
        )
    con.close()

    with MemoryStore(db) as store:
        cols = {
            r["name"] for r in store._con.execute("PRAGMA table_info(entries)")
        }
        assert "expires_at" in cols
        legacy = store.entries()[0]
        assert legacy.expires_at is None
        assert not is_expired(legacy)
        assert [e.id for e in ops.recall(store, "sqlite")] == [legacy.id]
        new = ops.retain(store, "new fact", expires_at=_iso(timedelta(days=1)))
        assert new.expires_at is not None
