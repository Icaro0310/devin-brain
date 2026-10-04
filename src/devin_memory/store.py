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

VALID_STATUSES = ("active", "proposed", "quarantined", "retracted")

_ENTRIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS entries (
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

_ENTRIES_INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at DESC, id DESC);
"""

ENTRIES_DDL = _ENTRIES_TABLE_DDL + _ENTRIES_INDEXES_DDL

# Columns added after the initial schema — applied via ALTER TABLE on open
# so existing memory.db files upgrade in place (additive only: new columns,
# no renames, no drops).
_MIGRATED_COLUMNS = {
    "machine_id": "TEXT",
    "profile": "TEXT",
    "conflicts_with": "INTEGER",
    "workspace": "TEXT",
}


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
    conflicts_with: int | None = None
    workspace: str | None = None

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
        conflicts_with=r["conflicts_with"],
        workspace=r["workspace"],
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
        """Upgrade databases created by earlier versions, in place.

        Two kinds of migration, both non-destructive:

        - new columns → plain ``ALTER TABLE ... ADD COLUMN`` (additive);
        - the ``status`` CHECK predating ``proposed`` → the canonical
          SQLite table rebuild (rename → recreate → ordered copy → drop).
          Rows are copied in ``id`` order so ``supersedes_id`` /
          ``conflicts_with`` references always point at an already-copied
          row under ``foreign_keys = ON``.
        """
        cols = {
            r["name"]
            for r in self._con.execute("PRAGMA table_info(entries)")
        }
        for col, decl in _MIGRATED_COLUMNS.items():
            if col not in cols:
                self._con.execute(
                    f"ALTER TABLE entries ADD COLUMN {col} {decl}"
                )
        row = self._con.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type = 'table' AND name = 'entries'"
        ).fetchone()
        if row is not None and "'proposed'" not in (row["sql"] or ""):
            self._rebuild_entries()

    def _rebuild_entries(self) -> None:
        """Recreate ``entries`` with the current DDL, preserving all rows."""
        cols = [
            r["name"]
            for r in self._con.execute("PRAGMA table_info(entries)")
        ]
        collist = ", ".join(cols)
        self._con.execute("ALTER TABLE entries RENAME TO entries_old")
        self._con.executescript(_ENTRIES_TABLE_DDL)
        self._con.execute(
            f"INSERT INTO entries({collist})"
            f" SELECT {collist} FROM entries_old ORDER BY id"
        )
        self._con.execute("DROP TABLE entries_old")
        # The old indexes kept their names on entries_old (skipped by
        # IF NOT EXISTS above) and were dropped with it — recreate them.
        self._con.executescript(_ENTRIES_INDEXES_DDL)

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
        conflicts_with: int | None = None,
        workspace: str | None = None,
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
                " quarantine_reasons, machine_id, profile, conflicts_with,"
                " workspace)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    conflicts_with,
                    workspace,
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

    def set_quarantine_reasons(
        self, entry_id: int, reasons: Iterable[str]
    ) -> None:
        """Replace the reasons list on a row (used by manual quarantine)."""
        with self._con:
            self._con.execute(
                "UPDATE entries SET quarantine_reasons = ? WHERE id = ?",
                (json.dumps(list(reasons)), entry_id),
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
        workspace: str | None = None,
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
        if workspace is None:
            workspace = old.workspace  # successors keep the same scope
        created_at = int(time.time() * 1000)
        with self._con:
            self._con.execute(
                "UPDATE entries SET status = 'retracted' WHERE id = ?",
                (old_id,),
            )
            cur = self._con.execute(
                "INSERT INTO entries(content, tags, source_session_id,"
                " source_rowid, created_at, status, version, supersedes_id,"
                " quarantine_reasons, machine_id, profile, conflicts_with,"
                " workspace)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    None,
                    workspace,
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
