"""``devin-memory diff A.db B.db`` — read-only divergence between two stores.

Two ``memory.db`` files (a live store vs a backup, two machines' stores)
are compared through the same serialized shape ``export_jsonl`` writes:
each side is opened with SQLite's ``file:...?mode=ro`` — never through
``MemoryStore``, whose open runs DDL/migrations — and every entry is
mapped by :func:`export._export_id` / :func:`export._to_line`, so keys
and compared payloads are exactly what a ``memories.jsonl`` consumer
would see. ``added`` (in B only), ``removed`` (in A only) and
``changed`` (same export id, different row) fall out of a plain dict
diff keyed by the stable 12-hex export id.

Entries carry their store row id + ``created_at`` inside the export id,
so the comparison is meaningful between copies/replicas of the same
store; two independently grown stores will simply diverge everywhere.

Nothing here writes: missing files raise ``FileNotFoundError`` (CLI
exit 2), unreadable stores raise :class:`DiffError` (exit 2), and the
databases themselves are never touched — no journal, no wal, no schema.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from devin_memory.export import _export_id, _to_line
from devin_memory.store import Entry

# Columns added by post-creation migrations — absent in older dbs.
_OPTIONAL_COLS = ("machine_id", "profile", "conflicts_with", "workspace")


class DiffError(ValueError):
    """A store could not be opened or its entries read."""


def _entry_from_row(row: sqlite3.Row) -> Entry:
    """``SELECT *`` row → :class:`Entry`, tolerating older schemas."""
    d = dict(row)
    for col in _OPTIONAL_COLS:
        d.setdefault(col, None)
    try:
        return Entry(
            id=d["id"],
            content=d["content"],
            tags=tuple(json.loads(d["tags"])),
            source_session_id=d["source_session_id"],
            source_rowid=d["source_rowid"],
            created_at=d["created_at"],
            status=d["status"],
            version=d["version"],
            supersedes_id=d["supersedes_id"],
            quarantine_reasons=tuple(json.loads(d["quarantine_reasons"])),
            machine_id=d["machine_id"],
            profile=d["profile"],
            conflicts_with=d["conflicts_with"],
            workspace=d["workspace"],
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DiffError(f"malformed entries row (id={d.get('id')}): {exc}") from exc


def _read_entries(db_path: str | Path) -> list[Entry]:
    """All ``entries`` rows from one store, opened strictly read-only."""
    path = Path(db_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DiffError(f"{path}: cannot open — {exc}") from exc
    try:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM entries").fetchall()
        except sqlite3.Error as exc:
            raise DiffError(f"{path}: cannot read entries — {exc}") from exc
    finally:
        con.close()
    return [_entry_from_row(r) for r in rows]


def _rows(entries: list[Entry], include_non_active: bool) -> dict[str, dict]:
    """export id → serialized JSONL row (the compared payload).

    ``supersedes`` resolves against export ids of *all* rows — same as
    ``export_jsonl`` — and ``None`` links are dropped, again matching the
    file shape. With ``include_non_active`` a ``status`` key is added so
    an active→retracted flip shows up as ``changed`` instead of being
    filtered out on both sides.
    """
    export_ids = {e.id: _export_id(e) for e in entries}
    out: dict[str, dict] = {}
    for e in entries:
        if not include_non_active and e.status != "active":
            continue
        row = _to_line(e, export_ids)
        if row.get("supersedes") is None:
            row.pop("supersedes", None)
        if include_non_active:
            row["status"] = e.status
        out[row["id"]] = row
    return out


def diff_stores(
    a_path: str | Path,
    b_path: str | Path,
    *,
    include_non_active: bool = False,
) -> dict:
    """added/removed/changed between two ``memory.db`` files, keyed by id.

    Returns the report dict; raises ``FileNotFoundError`` for a missing
    database and :class:`DiffError` for an unreadable one. Pure data —
    the CLI renders it as text or JSON.
    """
    a_entries = _read_entries(a_path)
    b_entries = _read_entries(b_path)
    a_rows = _rows(a_entries, include_non_active)
    b_rows = _rows(b_entries, include_non_active)

    added = [
        {"id": i, "row": b_rows[i]}
        for i in sorted(b_rows)
        if i not in a_rows
    ]
    removed = [
        {"id": i, "row": a_rows[i]}
        for i in sorted(a_rows)
        if i not in b_rows
    ]
    changed = []
    for i in sorted(a_rows):
        if i not in b_rows or a_rows[i] == b_rows[i]:
            continue
        fields = {
            k: {"a": a_rows[i].get(k), "b": b_rows[i].get(k)}
            for k in a_rows[i] | b_rows[i]
            if a_rows[i].get(k) != b_rows[i].get(k)
        }
        changed.append({"id": i, "fields": fields})
    return {
        "a": str(Path(a_path).expanduser()),
        "b": str(Path(b_path).expanduser()),
        "a_entries": len(a_rows),
        "b_entries": len(b_rows),
        "added": added,
        "removed": removed,
        "changed": changed,
        "different": bool(added or removed or changed),
    }


# ---------------------------------------------------------------------------
# text rendering
# ---------------------------------------------------------------------------


def _short(value: Any, width: int = 60) -> str:
    """Single-line repr-ish value for the text report."""
    if isinstance(value, str):
        text = " ".join(value.splitlines())
        shown = text if len(text) <= width else text[: width - 1] + "…"
        return f"'{shown}'"
    return json.dumps(value, ensure_ascii=False)


def render_text(report: dict) -> str:
    """Human-readable diff (ASCII-safe; truncated contents)."""
    lines = [
        "devin-memory diff",
        f"  A: {report['a']} ({report['a_entries']} entries)",
        f"  B: {report['b']} ({report['b_entries']} entries)",
        "",
    ]
    lines.append(f"added in B ({len(report['added'])}):")
    if report["added"]:
        for item in report["added"]:
            lines.append(
                f"  - {item['id']} {_short(item['row']['content'])}"
            )
    else:
        lines.append("  (none)")
    lines.append(f"removed from A ({len(report['removed'])}):")
    if report["removed"]:
        for item in report["removed"]:
            lines.append(
                f"  - {item['id']} {_short(item['row']['content'])}"
            )
    else:
        lines.append("  (none)")
    lines.append(f"changed ({len(report['changed'])}):")
    if report["changed"]:
        for item in report["changed"]:
            lines.append(f"  - {item['id']}")
            for field, pair in sorted(item["fields"].items()):
                lines.append(
                    f"      {field}: {_short(pair['a'], 38)}"
                    f" -> {_short(pair['b'], 38)}"
                )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("result: " + ("DIFFERENT" if report["different"] else "IDENTICAL"))
    return "\n".join(lines)
