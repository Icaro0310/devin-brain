"""Memory operations: retain, recall, retract, supersede, release, verify —
plus the F4 surface: manual quarantine, conflict links, session extraction
and ``prime`` context rendering.

All writes funnel through :func:`screen` first — the quarantine gate decides
the initial status. ``recall``/``prime`` only ever return ``active``
entries, so a poisoned fact cannot leak back into an agent's context.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from devin_internals.parsers import SessionsStore

from devin_memory import identity
from devin_memory.conflict import is_conflict
from devin_memory.extract import signals_from_nodes
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


def _find_conflict(store: MemoryStore, content: str) -> int | None:
    """Newest active entry contradicting ``content`` (or ``None``).

    Same normalized subject key + opposite polarity — see
    :mod:`devin_memory.conflict` for the heuristic and its limits.
    """
    for entry in store.entries(status="active"):
        if is_conflict(content, entry.content):
            return entry.id
    return None


def retain(
    store: MemoryStore,
    content: str,
    tags: Iterable[str] = (),
    source_session_id: str | None = None,
    source_rowid: int | None = None,
    machine_id: str | None = None,
    profile: str | None = None,
    workspace: str | None = None,
) -> Entry:
    """Screen ``content`` and store it with the resulting status.

    ``machine_id``/``profile`` default to this machine's opaque provenance
    (:mod:`devin_memory.identity`) — pass them only to reattribute an entry.

    If the new entry is active and contradicts an existing active entry
    (same subject, opposite directive), both are kept and the new row
    carries a ``conflicts_with`` link — a retain never silently replaces
    a prior belief (MM-2).
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    tag_list = _norm_tags(tags)
    result = screen(content, tag_list)
    conflicts_with = (
        _find_conflict(store, content) if result.status == "active" else None
    )
    return store.insert(
        content,
        tags=tag_list,
        status=result.status,
        quarantine_reasons=result.reasons,
        source_session_id=source_session_id,
        source_rowid=source_rowid,
        machine_id=machine_id,
        profile=profile,
        conflicts_with=conflicts_with,
        workspace=workspace,
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


def quarantine_entry(
    store: MemoryStore, entry_id: int, reason: str = "manual:user"
) -> Entry:
    """Mark an existing entry as ``quarantined`` (MM-3).

    Human-driven analogue of the write-time screen: an ``active`` or
    ``proposed`` entry the reviewer distrusts is moved to the quarantine
    lane. ``reason`` is appended to the row's reasons for audit (default
    ``manual:user``). Retracted entries cannot be quarantined — history
    stays history.
    """
    entry = _require(store, entry_id)
    if entry.status == "quarantined":
        if reason and reason not in entry.quarantine_reasons:
            store.set_quarantine_reasons(
                entry_id, [*entry.quarantine_reasons, reason]
            )
        return _require(store, entry_id)
    if entry.status == "retracted":
        raise InvalidTransitionError(
            f"entry {entry_id} is retracted; cannot quarantine history"
        )
    reasons = list(entry.quarantine_reasons)
    if reason and reason not in reasons:
        reasons.append(reason)
    store.set_quarantine_reasons(entry_id, reasons)
    store.set_status(entry_id, "quarantined")
    return _require(store, entry_id)


def approve(store: MemoryStore, entry_id: int) -> Entry:
    """Promote a ``proposed`` entry to ``active`` (MM-1 review step)."""
    entry = _require(store, entry_id)
    if entry.status != "proposed":
        raise InvalidTransitionError(
            f"entry {entry_id} is {entry.status}, not proposed"
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


# ---------------------------------------------------------------------------
# conflicts (MM-2)
# ---------------------------------------------------------------------------


def conflicts(store: MemoryStore) -> list[tuple[Entry, Entry]]:
    """(newer, older) entry pairs linked by ``conflicts_with``.

    Both sides stay in the store; recall sees whichever survives review.
    Resolve a pair with ``supersede``/``retract``/``quarantine_entry``.
    """
    pairs: list[tuple[Entry, Entry]] = []
    for entry in store.entries():
        if entry.conflicts_with is None:
            continue
        other = store.get(entry.conflicts_with)
        if other is not None:
            pairs.append((entry, other))
    return pairs


# ---------------------------------------------------------------------------
# extraction (MM-1)
# ---------------------------------------------------------------------------

EXTRACT_TAG = "extracted"


def extract_session(
    store: MemoryStore,
    sessions_db: str | Path,
    *,
    session_id: str | None = None,
    latest: bool = False,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """Mine one session for durable knowledge → ``proposed`` entries.

    Signal taxonomy lives in :mod:`devin_memory.extract`. Each candidate is
    screened like a normal retain: suspect sentences become ``quarantined``
    (never ``proposed``), clean ones become ``proposed`` — or ``active``
    with ``auto_approve=True``. Exact-content duplicates (against the whole
    store) are skipped so re-extraction is idempotent.

    The returned report lists ``{id, status, signals}`` per candidate —
    never the content, so a quarantined secret can't be echoed to stdout.
    """
    with SessionsStore(sessions_db) as sessions:
        if not session_id:
            if not latest:
                raise MemoryOpsError(
                    "extract needs a session id or --latest"
                )
            all_sessions = sessions.sessions()
            if not all_sessions:
                raise MemoryOpsError("sessions.db contains no sessions")
            session_id = all_sessions[0].id
        workspace = next(
            (s.working_directory for s in sessions.sessions()
             if s.id == session_id),
            None,
        )
        nodes = sessions.message_nodes(session_id=session_id)

    candidates = signals_from_nodes(nodes)
    seen = {e.content for e in store.entries()}
    report: dict[str, Any] = {
        "session_id": session_id,
        "sessions_db": str(sessions_db),
        "workspace": workspace,
        "nodes_scanned": len(nodes),
        "candidates": len(candidates),
        "skipped_duplicates": 0,
        "auto_approve": auto_approve,
        "items": [],
    }
    for cand in candidates:
        if cand.text in seen:
            report["skipped_duplicates"] += 1
            continue
        tags = _norm_tags(
            [EXTRACT_TAG, *(f"signal-{s}" for s in cand.signals)]
        )
        result = screen(cand.text, tags)
        if result.status == "quarantined":
            status, reasons = "quarantined", result.reasons
        else:
            status = "active" if auto_approve else "proposed"
            reasons = ()
        entry = store.insert(
            cand.text,
            tags=tags,
            status=status,
            quarantine_reasons=reasons,
            source_session_id=cand.session_id,
            source_rowid=cand.row_id,
            workspace=workspace,
        )
        seen.add(cand.text)
        report["items"].append(
            {
                "id": entry.id,
                "status": entry.status,
                "signals": list(cand.signals),
            }
        )
    return report


# ---------------------------------------------------------------------------
# prime (MM-4)
# ---------------------------------------------------------------------------

PRIME_HEADER = "# devin-memory: recalled context (heuristic)"
PRIME_DEFAULT_MAX_TOKENS = 1024
CHARS_PER_TOKEN = 4  # documented estimate — no tokenizer in stdlib


def _norm_workspace(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def prime(
    store: MemoryStore,
    *,
    workspace: str | None = None,
    profile: str | None = None,
    max_tokens: int = PRIME_DEFAULT_MAX_TOKENS,
) -> str:
    """Render a compact context block for a UserPromptSubmit hook.

    Only ``active`` entries are eligible — quarantined, proposed and
    retracted entries never surface. Filtering (heuristic, documented):

    - **workspace**: an entry scoped to a workspace only primes inside that
      workspace; unscoped entries are global. ``workspace=None`` means "no
      filter" (hook didn't provide one) and matches everything.
    - **profile**: an entry written under a different profile does not
      prime — the current profile defaults to
      :func:`identity.profile`, which fails closed to ``"corporate"``.

    Size is bounded by ``max_tokens`` using a ``chars / 4`` estimate;
    entries are emitted newest-first and smaller entries are packed in
    after larger ones stop fitting.
    """
    current_profile = profile or identity.profile()
    wanted_ws = _norm_workspace(workspace)
    eligible = [
        e
        for e in store.entries(status="active")
        if (e.profile is None or e.profile == current_profile)
        and (
            wanted_ws is None
            or e.workspace is None
            or _norm_workspace(e.workspace) == wanted_ws
        )
    ]

    budget = max(0, max_tokens) * CHARS_PER_TOKEN
    lines = [PRIME_HEADER]
    used = len(PRIME_HEADER) + 1
    shown = 0
    for entry in eligible:  # entries() is newest-first
        content = " ".join(entry.content.splitlines())
        line = f"- {content}"
        if used + len(line) + 1 > budget:
            continue  # a later, shorter entry may still fit
        lines.append(line)
        used += len(line) + 1
        shown += 1
    if not shown:
        lines.append("(no active memories)")
    return "\n".join(lines) + "\n"
