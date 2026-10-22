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
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

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
  workspace TEXT,
  expires_at TEXT
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
    "expires_at": "TEXT",
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
    expires_at: str | None = None  # ISO-8601; None = never expires

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
        expires_at=r["expires_at"],
    )


def parse_expires_at(value: str) -> float:
    """Validate an ISO-8601 ``expires_at`` and return epoch milliseconds.

    Accepts anything :func:`datetime.fromisoformat` reads (date-only
    allowed, meaning midnight) plus a trailing ``Z``/``z`` — fromisoformat
    only learned ``Z`` in 3.11 and the floor here is 3.10. Naive values
    are read as UTC. Raises :class:`ValueError` on malformed input: every
    write path validates eagerly so bad values never reach a row through
    the API.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expires_at must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"malformed expires_at {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000


def is_expired(entry: Entry, now_ms: float | None = None) -> bool:
    """True when ``entry.expires_at`` is set and its moment has passed.

    A stored value that fails to parse fails *open* (treated as
    non-expiring): every write validates, so a malformed value can only
    come from a hand-edited row — and a corrupt TTL must not silently
    drop a memory from recall. ``list``/``get`` still surface the raw
    value for cleanup.
    """
    if entry.expires_at is None:
        return False
    try:
        expiry_ms = parse_expires_at(entry.expires_at)
    except ValueError:
        return False
    now = time.time() * 1000 if now_ms is None else now_ms
    return expiry_ms <= now


_RELATIVE_SINCE_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
_RELATIVE_UNIT_MS = {
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}


def parse_since(value: str, now_ms: float | None = None) -> float:
    """Parse a ``--since`` spec into an epoch-ms ``created_at`` cutoff.

    Two forms:

    - a relative duration — ``30s``, ``15m``, ``24h``, ``7d``, ``2w``
      (case-insensitive) — meaning "this far back from now";
      ``now_ms`` is injectable for tests;
    - an ISO-8601 date/datetime — same grammar and naive-means-UTC
      convention as :func:`parse_expires_at`.

    Anything else raises :class:`ValueError` so a typoed filter fails
    loudly instead of silently widening to "everything".
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "since must be a non-empty ISO-8601 date or duration"
        )
    text = value.strip()
    m = _RELATIVE_SINCE_RE.match(text)
    if m:
        base = time.time() * 1000 if now_ms is None else now_ms
        return base - int(m.group(1)) * _RELATIVE_UNIT_MS[m.group(2).lower()]
    try:
        return parse_expires_at(text)
    except ValueError:
        raise ValueError(
            f"malformed since {value!r}: use an ISO-8601 date or a"
            " duration like 24h / 7d"
        ) from None


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

    @contextmanager
    def _unit(self) -> Iterator[None]:
        """Scope of one write unit.

        A standalone write self-commits (each helper stays atomic on its
        own); inside :meth:`transaction` it joins the open transaction
        instead, so a compound caller commits once at the end — never
        midway through a multi-step update.
        """
        if self._con.in_transaction:
            yield
        else:
            with self._con:
                yield

    @contextmanager
    def transaction(self) -> Iterator[MemoryStore]:
        """Hold one ``IMMEDIATE`` write transaction across operations.

        The write helpers (:meth:`insert`, :meth:`set_status`,
        :meth:`set_tags`, :meth:`set_quarantine_reasons`,
        :meth:`supersede`) join the open transaction instead of
        committing per call; the block commits once on clean exit and
        rolls back on error. ``BEGIN IMMEDIATE`` takes the write lock up
        front, so a read-modify-write (e.g. ``compact --apply``) cannot
        race another writer between planning and mutating. ``VACUUM``
        cannot run inside it — call :meth:`vacuum` after the block.
        """
        if self._con.in_transaction:
            yield self  # nested call: join the outer transaction
            return
        self._con.execute("BEGIN IMMEDIATE")
        try:
            yield self
        except BaseException:
            self._con.rollback()
            raise
        else:
            self._con.commit()

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
        expires_at: str | None = None,
    ) -> Entry:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        if expires_at is not None:
            parse_expires_at(expires_at)  # ValueError on malformed
        if machine_id is None or profile is None:
            prov = identity.provenance()
            machine_id = machine_id if machine_id is not None else prov["machine_id"]
            profile = profile if profile is not None else prov["profile"]
        created_at = int(time.time() * 1000)
        with self._unit():
            cur = self._con.execute(
                "INSERT INTO entries(content, tags, source_session_id,"
                " source_rowid, created_at, status, version, supersedes_id,"
                " quarantine_reasons, machine_id, profile, conflicts_with,"
                " workspace, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    expires_at,
                ),
            )
        entry = self.get(cur.lastrowid)
        assert entry is not None  # just inserted
        return entry

    def set_status(self, entry_id: int, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        with self._unit():
            self._con.execute(
                "UPDATE entries SET status = ? WHERE id = ?",
                (status, entry_id),
            )

    def set_quarantine_reasons(
        self, entry_id: int, reasons: Iterable[str]
    ) -> None:
        """Replace the reasons list on a row (used by manual quarantine)."""
        with self._unit():
            self._con.execute(
                "UPDATE entries SET quarantine_reasons = ? WHERE id = ?",
                (json.dumps(list(reasons)), entry_id),
            )

    def set_tags(self, entry_id: int, tags: Iterable[str]) -> None:
        """Replace the tags list on a row (used by ``compact`` merges)."""
        with self._unit():
            self._con.execute(
                "UPDATE entries SET tags = ? WHERE id = ?",
                (json.dumps(list(tags)), entry_id),
            )

    def set_expires_at(self, entry_id: int, expires_at: str | None) -> None:
        """Set an entry's ISO-8601 expiry, or clear it with ``None``.

        A non-None value is validated like a write — malformed input
        raises :class:`ValueError` before the row is touched.
        """
        if expires_at is not None:
            parse_expires_at(expires_at)
        with self._unit():
            self._con.execute(
                "UPDATE entries SET expires_at = ? WHERE id = ?",
                (expires_at, entry_id),
            )

    # -- maintenance -----------------------------------------------------------

    def freelist_bytes(self) -> int:
        """Bytes sitting on SQLite's free page list — what ``VACUUM``
        could reclaim (an estimate; index pages also compact)."""
        pages = self._con.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = self._con.execute("PRAGMA page_size").fetchone()[0]
        return int(pages) * int(page_size)

    def vacuum(self) -> None:
        """Rebuild the database file in place, reclaiming free pages.

        Runs outside a transaction (SQLite requirement); rows are never
        rewritten semantically — this is pure file compaction.
        """
        self._con.execute("VACUUM")

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
        expires_at: str | None = None,
    ) -> Entry:
        """Atomically retract ``old_id`` and insert its successor (version+1).

        ``expires_at=None`` inherits the old row's TTL (successors keep
        the same expiry, like workspace); pass a new ISO value to change
        it, and :meth:`set_expires_at` on the new id to clear it.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        old = self.get(old_id)
        if old is None:
            raise KeyError(old_id)
        if expires_at is None:
            expires_at = old.expires_at
        else:
            parse_expires_at(expires_at)  # ValueError on malformed
        if machine_id is None or profile is None:
            prov = identity.provenance()
            machine_id = machine_id if machine_id is not None else prov["machine_id"]
            profile = profile if profile is not None else prov["profile"]
        if workspace is None:
            workspace = old.workspace  # successors keep the same scope
        created_at = int(time.time() * 1000)
        with self._unit():
            self._con.execute(
                "UPDATE entries SET status = 'retracted' WHERE id = ?",
                (old_id,),
            )
            cur = self._con.execute(
                "INSERT INTO entries(content, tags, source_session_id,"
                " source_rowid, created_at, status, version, supersedes_id,"
                " quarantine_reasons, machine_id, profile, conflicts_with,"
                " workspace, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    expires_at,
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
        self,
        status: str | None = None,
        limit: int | None = None,
        since: float | None = None,
    ) -> list[Entry]:
        """Entries newest-first; optionally filtered by status and/or a
        ``created_at >= since`` epoch-ms cutoff."""
        sql = "SELECT * FROM entries"
        args: list[Any] = []
        clauses: list[str] = []
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status {status!r}")
            clauses.append("status = ?")
            args.append(status)
        if since is not None:
            clauses.append("created_at >= ?")
            args.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
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
