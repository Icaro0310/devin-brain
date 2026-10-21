"""Memory operations: retain, recall, retract, supersede, release, verify —
plus the F4 surface: manual quarantine, conflict links, session extraction
and ``prime`` context rendering — and store maintenance: ``compact``
(dedup + vacuum) and the ``quarantine_digest`` audit hash.

All writes funnel through :func:`screen` first — the quarantine gate decides
the initial status. ``recall``/``prime`` only ever return ``active``
entries, so a poisoned fact cannot leak back into an agent's context.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from devin_internals.parsers import SessionsStore

from devin_memory import identity
from devin_memory.conflict import is_conflict
from devin_memory.extract import signals_from_nodes
from devin_memory.screen import (
    INJECTION_PATTERNS,
    SECRET_PATTERNS,
    screen,
)
from devin_memory.store import Entry, MemoryStore, is_expired


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
    expires_at: str | None = None,
) -> Entry:
    """Screen ``content`` and store it with the resulting status.

    ``machine_id``/``profile`` default to this machine's opaque provenance
    (:mod:`devin_memory.identity`) — pass them only to reattribute an entry.
    ``expires_at`` is an optional ISO-8601 timestamp: once it passes, the
    entry stops surfacing in ``recall``/``prime`` (the row stays for
    audit). Malformed values raise :class:`ValueError` like any bad write.

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
        expires_at=expires_at,
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


# Recall ranking: keyword score × exponential recency decay — a memory's
# weight halves every ``RECALL_DECAY_HALF_LIFE_DAYS`` of age, so a fresh
# entry outranks a stale one unless the stale hit is much stronger.
RECALL_DECAY_HALF_LIFE_DAYS = 30.0
_DAY_MS = 86_400_000


def _recency_decay(
    entry: Entry, now_ms: float, half_life_days: float | None
) -> float:
    """``1.0`` at write time, ``0.5 ** (age / half_life)`` afterwards.

    ``None`` or non-positive ``half_life_days`` disables decay; future
    ``created_at`` (clock skew) clamps to age 0, never a boost past 1.
    """
    if not half_life_days or half_life_days <= 0:
        return 1.0
    age_ms = max(0.0, now_ms - entry.created_at)
    return 0.5 ** (age_ms / (half_life_days * _DAY_MS))


def recall(
    store: MemoryStore,
    query: str = "",
    limit: int = 5,
    tags: Iterable[str] | None = None,
    *,
    include_expired: bool = False,
    half_life_days: float | None = RECALL_DECAY_HALF_LIFE_DAYS,
) -> list[Entry]:
    """Keyword-ranked recall over ``active`` entries only.

    Entries whose ``expires_at`` has passed are excluded by default —
    same filtered-view contract as quarantined/retracted rows (``list``
    and ``get`` still see them); ``include_expired=True`` opts out.

    Relevance is the keyword score weighted by an exponential recency
    decay on ``created_at`` age (halving every ``half_life_days``), so
    fresher memories win ties and mildly outrank stronger-but-stale hits
    as the gap in age grows. ``half_life_days=None`` (or 0) restores pure
    score ordering. Empty ``query`` returns the most recent entries —
    already recency-ordered, so decay changes nothing there. ``tags``
    restricts to entries sharing at least one tag.
    """
    now_ms = time.time() * 1000
    candidates = store.entries(status="active")
    if not include_expired:
        candidates = [e for e in candidates if not is_expired(e, now_ms)]
    if tags is not None:
        wanted = {t.strip().lower() for t in tags if t.strip()}
        candidates = [
            e for e in candidates
            if wanted & {t.lower() for t in e.tags}
        ]
    terms = _terms(query)
    if terms:
        scored = {
            e.id: _score(e, terms) * _recency_decay(e, now_ms, half_life_days)
            for e in candidates
        }
        ranked = [e for e in candidates if scored[e.id] > 0]
        ranked.sort(key=lambda e: (-scored[e.id], -e.created_at, -e.id))
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
    expires_at: str | None = None,
) -> Entry:
    """Replace an active entry with a corrected version (history kept).

    The old row becomes ``retracted`` and the new row links back via
    ``supersedes_id``/``version``. The new content is screened like any
    other retain — if it quarantines, the old version is still retired
    (the replacement waits in the queue for review). ``expires_at=None``
    keeps the old row's expiry; pass a new ISO timestamp to change it.
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
        expires_at=expires_at,
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

    Only ``active``, unexpired entries are eligible — quarantined,
    proposed, retracted and past-``expires_at`` entries never surface
    (same filtered-view contract as :func:`recall`). Filtering
    (heuristic, documented):

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
    now_ms = time.time() * 1000
    eligible = [
        e
        for e in store.entries(status="active")
        if (e.profile is None or e.profile == current_profile)
        and (
            wanted_ws is None
            or e.workspace is None
            or _norm_workspace(e.workspace) == wanted_ws
        )
        and not is_expired(e, now_ms)
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


# ---------------------------------------------------------------------------
# quarantine digest (audit)
# ---------------------------------------------------------------------------

# Reason strings the audit digest may report verbatim — the closed
# ``family:name`` taxonomy emitted by :func:`screen`. Anything else is
# free-form: ``--reason`` accepts arbitrary text, including a spoofed
# family prefix like ``secret:<password>``, so unknown members bucket as
# ``<family>:other`` and never echo their payload. Screen reasons added
# later fail closed the same way — under-detailed, never leaky.
_AUDIT_KNOWN_REASONS = frozenset(
    [f"secret:{name}" for name in SECRET_PATTERNS]
    + [f"injection:{name}" for name in INJECTION_PATTERNS]
    + [
        "limit:content_too_large",
        "limit:too_many_tags",
        "shape:bad_tag",
        "shape:nul_byte",
        "shape:long_base64_run",
    ]
)
_AUDIT_REASON_FAMILIES = ("secret", "injection", "limit", "shape")


def _reason_audit_key(reason: str) -> str:
    if reason in _AUDIT_KNOWN_REASONS:
        return reason
    family = reason.split(":", 1)[0]
    if family == "manual":
        return "manual:*"
    if family in _AUDIT_REASON_FAMILIES:
        return f"{family}:other"
    return "other"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry_fingerprint(entry: Entry) -> str:
    """Content-keyed fingerprint of one entry — no ids, so two machines
    holding the same quarantined fact produce the same print."""
    content_sha = _sha256_hex(entry.content)
    # A JSON array is length-delimited: a separator inside a free-form
    # reason can't alias two different reason lists into one hash the
    # way a plain "\n".join can.
    reasons_sha = _sha256_hex(json.dumps(sorted(entry.quarantine_reasons)))
    return _sha256_hex(f"{content_sha}:{reasons_sha}")


def quarantine_digest(store: MemoryStore) -> dict[str, Any]:
    """Deterministic audit digest of the quarantine lane (read-only).

    ``digest`` is sha256 over the sorted per-entry fingerprints — each
    fingerprint is sha256 of ``sha256(content) : sha256(JSON of sorted
    reasons)`` — the JSON array keeps reason boundaries unambiguous.
    Because prints key on content (not row ids), two stores holding the same
    quarantined entries produce the same digest regardless of insertion
    order, and any membership or reason change moves the digest. An empty
    lane digests to sha256("").

    The report carries counts and taxonomy-level reason buckets only —
    content and free-form reason text never appear in the output.
    """
    entries = store.entries(status="quarantined")
    reason_counts: dict[str, int] = {}
    for entry in entries:
        for reason in entry.quarantine_reasons:
            key = _reason_audit_key(reason)
            reason_counts[key] = reason_counts.get(key, 0) + 1
    fingerprints = sorted(_entry_fingerprint(e) for e in entries)
    return {
        "status": "quarantined",
        "count": len(entries),
        "reason_counts": dict(sorted(reason_counts.items())),
        "algorithm": "sha256",
        "digest": _sha256_hex("\n".join(fingerprints)),
    }


# ---------------------------------------------------------------------------
# compact (dedup + vacuum)
# ---------------------------------------------------------------------------

# Survivor preference inside a duplicate group: the most "live" status wins
# so compacting never pushes a fact out of recall; ties keep the oldest row.
_COMPACT_STATUS_RANK = {"active": 0, "proposed": 1, "quarantined": 2}


def _db_file_bytes(store: MemoryStore) -> int | None:
    """Size of the db file in bytes (``None`` for ``:memory:`` stores)."""
    if str(store.path) == ":memory:":
        return None
    try:
        return store.path.stat().st_size
    except OSError:
        return None


def _dedup_groups(entries: list[Entry]) -> list[list[Entry]]:
    """Groups of ≥2 non-retracted entries sharing (content, workspace,
    profile).

    ``retracted`` rows are history, not duplicates — a withdrawn fact
    re-retained later is a distinct event, so they never join a group.
    ``workspace`` and ``profile`` are compared raw: dedup never crosses
    scope boundaries, and ``prime`` only surfaces entries matching the
    current profile, so merging across profiles could retract the only
    copy a profile still sees.
    """
    by_key: dict[tuple[str, str | None, str | None], list[Entry]] = {}
    for entry in entries:
        if entry.status == "retracted":
            continue
        by_key.setdefault(
            (entry.content, entry.workspace, entry.profile), []
        ).append(entry)
    return [members for members in by_key.values() if len(members) > 1]


def _dedup_survivor(members: list[Entry]) -> Entry:
    return min(
        members,
        key=lambda e: (_COMPACT_STATUS_RANK.get(e.status, 99), e.id),
    )


def _group_report(survivor: Entry, members: list[Entry]) -> dict[str, Any]:
    """Report view of one duplicate group — ids and a truncated content
    hash only, never the content itself."""
    return {
        "keep_id": survivor.id,
        "status": survivor.status,
        "drop_ids": [e.id for e in members if e.id != survivor.id],
        "content_sha256": _sha256_hex(members[0].content)[:12],
        "workspace": survivor.workspace,
    }


def _apply_dedup(store: MemoryStore) -> list[dict[str, Any]]:
    """Re-plan and execute dedup; the caller holds the write transaction.

    Groups are recomputed from fresh state under the lock, so a retraction
    (or a new copy) committed between the dry-run plan and ``--apply``
    cannot leave dedup retracting the last live version of a fact.
    """
    applied: list[dict[str, Any]] = []
    for members in _dedup_groups(store.entries()):
        members = sorted(members, key=lambda e: e.id)
        survivor = _dedup_survivor(members)
        drops = [e for e in members if e.id != survivor.id]
        # Tags merge only across copies sharing the survivor's status —
        # quarantined/proposed tags never bleed into an active survivor,
        # so unreviewed metadata cannot reach recall through compact.
        merged_tags = _norm_tags(
            [
                *survivor.tags,
                *(
                    t
                    for d in drops
                    if d.status == survivor.status
                    for t in d.tags
                ),
            ]
        )
        if merged_tags != list(survivor.tags):
            store.set_tags(survivor.id, merged_tags)
        if survivor.status == "quarantined":
            merged_reasons: dict[str, None] = {}
            for reason in [
                *survivor.quarantine_reasons,
                *(r for d in drops for r in d.quarantine_reasons),
            ]:
                merged_reasons.setdefault(reason)
            if list(merged_reasons) != list(survivor.quarantine_reasons):
                store.set_quarantine_reasons(
                    survivor.id, list(merged_reasons)
                )
        for drop in drops:
            store.set_status(drop.id, "retracted")
        applied.append(_group_report(survivor, members))
    applied.sort(key=lambda g: g["keep_id"])
    return applied


def compact(store: MemoryStore, *, apply: bool = False) -> dict[str, Any]:
    """Deduplicate the store; dry-run by default, mutates only with ``apply``.

    A duplicate group is ≥2 non-retracted entries with identical
    ``content``, ``workspace`` and ``profile``. The survivor is the entry
    with the liveliest status (``active`` > ``proposed`` >
    ``quarantined``), ties broken by lowest id; every other copy becomes
    ``retracted`` — rows are never deleted, so provenance and reasons
    stay auditable on the retracted rows. The survivor inherits the union
    of the group's tags (recall surface) and, when quarantined, the union
    of quarantine reasons (review accuracy).

    With ``apply=True`` the dedup re-plans and executes inside a single
    write transaction — either every group merges or none does, and a
    concurrent retraction cannot trick dedup into removing the last live
    copy. ``VACUUM`` then runs after the commit (SQLite forbids it inside
    a transaction) — the only byte savings available, since dedup itself
    deletes nothing. A vacuum failure is reported via
    ``vacuumed``/``vacuum_error`` without masking the committed dedup,
    and in apply mode ``groups`` reflects what was actually merged, which
    can differ from the dry-run plan if the store changed in between.
    The report never prints content; groups are identified by
    ``keep_id``/``drop_ids`` and a truncated content sha256.
    """
    entries = store.entries()
    live = [e for e in entries if e.status != "retracted"]
    groups: list[dict[str, Any]] = []
    for members in _dedup_groups(entries):
        members = sorted(members, key=lambda e: e.id)
        groups.append(_group_report(_dedup_survivor(members), members))
    groups.sort(key=lambda g: g["keep_id"])
    dropped = sum(len(g["drop_ids"]) for g in groups)
    report: dict[str, Any] = {
        "dry_run": not apply,
        "entries_total": len(entries),
        "entries_live": len(live),
        "entries_live_after": len(live) - dropped,
        "duplicate_groups": len(groups),
        "duplicate_entries": dropped,
        "groups": groups,
        "db_bytes_before": _db_file_bytes(store),
        "freelist_bytes": store.freelist_bytes(),
        "db_bytes_after": None,
        "vacuumed": False,
        "vacuum_error": None,
    }
    if not apply:
        return report

    with store.transaction():
        report["groups"] = _apply_dedup(store)
    report["duplicate_groups"] = len(report["groups"])
    report["duplicate_entries"] = sum(
        len(g["drop_ids"]) for g in report["groups"]
    )
    report["entries_live_after"] = len(
        [e for e in store.entries() if e.status != "retracted"]
    )
    try:
        store.vacuum()
        report["vacuumed"] = True
    except sqlite3.Error as exc:
        report["vacuum_error"] = str(exc)
    report["db_bytes_after"] = _db_file_bytes(store)
    return report
