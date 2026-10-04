"""``memory.db`` — devin-memory's own SQLite store.

This is the only store in the ecosystem that *writes*, and it writes only to
its own database — never to Devin's stores (``sessions.db``,
``acp-messages/*.db``, ``state.vscdb`` stay read-only via devin-internals).

Each row is a durable memory entry with provenance (which Devin session and
message row produced it), a version/supersedes chain, a status
(``active`` | ``quarantined`` | ``retracted``) and the screening reasons that
put it in quarantine (kept even after release, for audit).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from devin_memory import identity

VALID_STATUSES = ("active", "quarantined", "retracted")

ENTRIES_DDL = """
CREATE TABLE IF NOT EXISTS entries (
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
CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at DESC, id DESC);
"""

# Columns added after the initial schema — applied via ALTER TABLE on open
# so existing memory.db files upgrade in place.
_MIGRATED_COLUMNS = ("machine_id", "profile")


@dataclass(frozen=True)
class Entry:
    """One memory row. ``created_at`` is epoch milliseconds (Devin convention)."""

    id: int
    content: str
    tags: tuple[str, ...]
    source_session_id: str | None
    source_rowid: int | None
    created_at: int
    status: str
    version: int
    supersedes_id: int | None
    quarantine_reasons: tuple[str, ...]
    machine_id: str | None = None
    profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = list(self.tags)
        d["quarantine_reasons"] = list(self.quarantine_reasons)
        return d


def _row_to_entry(r: sqlite3.Row) -> Entry:
    return Entry(
        id=r["id"],
        content=r["content"],
        tags=tuple(json.loads(r["tags"])),
        source_session_id=r["source_session_id"],
        source_rowid=r["source_rowid"],
        created_at=r["created_at"],
        status=r["status"],
        version=r["version"],
        supersedes_id=r["supersedes_id"],
        quarantine_reasons=tuple(json.loads(r["quarantine_reasons"])),
        machine_id=r["machine_id"],
        profile=r["profile"],
    )


class MemoryStore:
    """Read-write handle on a ``memory.db`` file (or ``":memory:"``)."""

    def __init__(self, db_path: str | Path) -> None:
        raw = str(db_path)
        if raw == ":memory:":
            self.path = Path(":memory:")
            self._con = sqlite3.connect(":memory:")
        else:
            self.path = Path(db_path).expanduser()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(self.path)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        with self._con:
            self._con.executescript(ENTRIES_DDL)
            self._migrate()

    def _migrate(self) -> None:
        """Add post-v1 columns to databases created before they existed."""
        cols = {
            r["name"]
            for r in self._con.execute("PRAGMA table_info(entries)")
        }
        for col in _MIGRATED_COLUMNS:
            if col not in cols:
                self._con.execute(
                    f"ALTER TABLE entries ADD COLUMN {col} TEXT"
                )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writes --------------------------------------------------------------

    def insert(
        self,
        content: str,
        *,
        tags: Iterable[str] = (),
        status: str = "active",
        version: int = 1,
        supersedes_id: int | None = None,
        quarantine_reasons: Iterable[str] = (),
        source_session_id: str | None = None,
        source_rowid: int | None = None,
        machine_id: str | None = None,
        profile: str | None = None,
    ) -> Entry:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        if machine_id is None or profile is None:
            prov = identity.provenance()
            machine_id = machine_id if machine_id is not None else prov["machine_id"]
            profile = profile if profile is not None else prov["profile"]
        created_at = int(time.time() * 1000)
        with self._con:
            cur = self._con.execute(
                "INSERT INTO entries(content, tags, source_session_id,"
                " source_rowid, created_at, status, version, supersedes_id,"
                " quarantine_reasons, machine_id, profile)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    content,
                    json.dumps(list(tags)),
                    source_session_id,
                    source_rowid,
                    created_at,
                    status,
                    version,
                    supersedes_id,
                    json.dumps(list(quarantine_reasons)),
                    machine_id,
                    profile,
                ),
            )
        entry = self.get(cur.lastrowid)
        assert entry is not None  # just inserted
        return entry

    def set_status(self, entry_id: int, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        with self._con:
            self._con.execute(
                "UPDATE entries SET status = ? WHERE id = ?",
                (status, entry_id),
            )

    def supersede(
        self,
        old_id: int,
        content: str,
        *,
        tags: Iterable[str] = (),
        status: str = "active",
        quarantine_reasons: Iterable[str] = (),
        source_session_id: str | None = None,
        source_rowid: int | None = None,
        machine_id: str | None = None,
        profile: str | None = None,
    ) -> Entry:
        """Atomically retract ``old_id`` and insert its successor (version+1)."""
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        old = self.get(old_id)
        if old is None:
            raise KeyError(old_id)
        if machine_id is None or profile is None:
            prov = identity.provenance()
            machine_id = machine_id if machine_id is not None else prov["machine_id"]
            profile = profile if profile is not None else prov["profile"]
        created_at = int(time.time() * 1000)
        with self._con:
            self._con.execute(
                "UPDATE entries SET status = 'retracted' WHERE id = ?",
                (old_id,),
            )
            cur = self._con.execute(
                "INSERT INTO entries(content, tags, source_session_id,"
                " source_rowid, created_at, status, version, supersedes_id,"
                " quarantine_reasons, machine_id, profile)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    content,
                    json.dumps(list(tags)),
                    source_session_id,
                    source_rowid,
                    created_at,
                    status,
                    old.version + 1,
                    old_id,
                    json.dumps(list(quarantine_reasons)),
                    machine_id,
                    profile,
                ),
            )
        entry = self.get(cur.lastrowid)
        assert entry is not None
        return entry

    # -- reads ----------------------------------------------------------------

    def get(self, entry_id: int) -> Entry | None:
        row = self._con.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_entry(row) if row is not None else None

    def entries(
        self, status: str | None = None, limit: int | None = None
    ) -> list[Entry]:
        """Entries newest-first; optionally filtered by status."""
        sql = "SELECT * FROM entries"
        args: list[Any] = []
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status {status!r}")
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [_row_to_entry(r) for r in self._con.execute(sql, args)]

    def counts(self) -> dict[str, int]:
        rows = self._con.execute(
            "SELECT status, COUNT(*) FROM entries GROUP BY status"
        )
        counts = {s: 0 for s in VALID_STATUSES}
        counts.update({r["status"]: r[1] for r in rows})
        return counts
