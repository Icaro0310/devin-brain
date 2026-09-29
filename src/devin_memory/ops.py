"""Memory operations: retain, recall, retract, supersede, release, verify.

All writes funnel through :func:`screen` first — the quarantine gate decides
the initial status. ``recall`` only ever returns ``active`` entries, so a
poisoned fact cannot leak back into an agent's context.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from devin_internals.parsers import SessionsStore

from devin_memory.screen import screen
from devin_memory.store import Entry, MemoryStore


class MemoryOpsError(RuntimeError):
    """Base class for ops failures."""


class EntryNotFoundError(MemoryOpsError, KeyError):
    """No entry with this id."""


class InvalidTransitionError(MemoryOpsError):
    """The requested status transition is not legal for this entry."""


def _require(store: MemoryStore, entry_id: int) -> Entry:
    entry = store.get(entry_id)
    if entry is None:
        raise EntryNotFoundError(f"no entry with id {entry_id}")
    return entry


def _norm_tags(tags: Iterable[str]) -> list[str]:
    """Strip, drop empties, dedupe preserving order."""
    seen: dict[str, None] = {}
    for t in tags:
        t = t.strip()
        if t:
            seen.setdefault(t)
    return list(seen)


def retain(
    store: MemoryStore,
    content: str,
    tags: Iterable[str] = (),
    source_session_id: str | None = None,
    source_rowid: int | None = None,
) -> Entry:
    """Screen ``content`` and store it with the resulting status."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    tag_list = _norm_tags(tags)
    result = screen(content, tag_list)
    return store.insert(
        content,
        tags=tag_list,
        status=result.status,
        quarantine_reasons=result.reasons,
        source_session_id=source_session_id,
        source_rowid=source_rowid,
    )


def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if t]


def _score(entry: Entry, terms: list[str]) -> float:
    """Deterministic keyword score (primitive on purpose — no embeddings)."""
    content = entry.content.lower()
    score = 0.0
    for term in terms:
        occ = content.count(term)
        if occ:
            score += 2.0 + min(occ, 5) - 1  # 2 for the hit, +1/extra (cap 5)
        lowered = [t.lower() for t in entry.tags]
        if term in lowered:
            score += 3.0
        elif any(term in t for t in lowered):
            score += 1.0
    return score


def recall(
    store: MemoryStore,
    query: str = "",
    limit: int = 5,
    tags: Iterable[str] | None = None,
) -> list[Entry]:
    """Keyword-ranked recall over ``active`` entries only.

    Empty ``query`` returns the most recent entries. ``tags`` restricts to
    entries sharing at least one tag.
    """
    candidates = store.entries(status="active")
    if tags is not None:
        wanted = {t.strip().lower() for t in tags if t.strip()}
        candidates = [
            e for e in candidates
            if wanted & {t.lower() for t in e.tags}
        ]
    terms = _terms(query)
    if terms:
        scored = [(e, _score(e, terms)) for e in candidates]
        ranked = [e for e, s in scored if s > 0]
        ranked.sort(key=lambda e: (-_score(e, terms), -e.created_at, -e.id))
    else:
        ranked = candidates
    return ranked[:limit]


def retract(store: MemoryStore, entry_id: int) -> Entry:
    """Withdraw an entry (kept for history; recall never returns it)."""
    entry = _require(store, entry_id)
    if entry.status == "retracted":
        raise InvalidTransitionError(f"entry {entry_id} is already retracted")
    store.set_status(entry_id, "retracted")
    return _require(store, entry_id)


def release(store: MemoryStore, entry_id: int) -> Entry:
    """Human override: move a ``quarantined`` entry to ``active``.

    The quarantine reasons stay on the row — release is an audit event,
    not an erasure.
    """
    entry = _require(store, entry_id)
    if entry.status != "quarantined":
        raise InvalidTransitionError(
            f"entry {entry_id} is {entry.status}, not quarantined"
        )
    store.set_status(entry_id, "active")
    return _require(store, entry_id)


def supersede(
    store: MemoryStore,
    entry_id: int,
    content: str,
    tags: Iterable[str] | None = None,
    source_session_id: str | None = None,
    source_rowid: int | None = None,
) -> Entry:
    """Replace an active entry with a corrected version (history kept).

    The old row becomes ``retracted`` and the new row links back via
    ``supersedes_id``/``version``. The new content is screened like any
    other retain — if it quarantines, the old version is still retired
    (the replacement waits in the queue for review).
    """
    old = _require(store, entry_id)
    if old.status != "active":
        raise InvalidTransitionError(
            f"entry {entry_id} is {old.status}; only active entries "
            "can be superseded"
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    tag_list = _norm_tags(old.tags if tags is None else tags)
    result = screen(content, tag_list)
    return store.supersede(
        entry_id,
        content,
        tags=tag_list,
        status=result.status,
        quarantine_reasons=result.reasons,
        source_session_id=source_session_id or old.source_session_id,
        source_rowid=source_rowid if source_rowid is not None else old.source_rowid,
    )


def list_entries(
    store: MemoryStore, status: str | None = None, limit: int | None = None
) -> list[Entry]:
    return store.entries(status=status, limit=limit)


def verify_provenance(
    store: MemoryStore, entry_id: int, sessions_db: str | Path
) -> dict[str, Any]:
    """Check an entry's provenance against a real ``sessions.db``.

    Uses devin-internals' read-only ``SessionsStore``: the recorded
    ``source_session_id`` must exist as a session, and ``source_rowid``
    (when recorded) must exist as a ``message_nodes.row_id`` in that
    session — the "which session, when, evidence" audit.
    """
    entry = _require(store, entry_id)
    report: dict[str, Any] = {
        "entry_id": entry.id,
        "sessions_db": str(sessions_db),
        "source_session_id": entry.source_session_id,
        "source_rowid": entry.source_rowid,
        "checked": False,
        "session_found": None,
        "rowid_found": None,
    }
    if not entry.source_session_id:
        report["reason"] = "no provenance recorded on this entry"
        return report

    with SessionsStore(sessions_db) as sessions:
        known = {s.id for s in sessions.sessions()}
        found = entry.source_session_id in known
        report["session_found"] = found
        if entry.source_rowid is not None:
            if found:
                rowids = {
                    n.row_id
                    for n in sessions.message_nodes(
                        session_id=entry.source_session_id
                    )
                }
                report["rowid_found"] = entry.source_rowid in rowids
            else:
                report["rowid_found"] = False
    report["checked"] = True
    return report
