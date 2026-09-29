"""Export active memories to ``memories.jsonl``.

Line shape is compatible with the Devin memory MCP (the same one that
writes ``.devin/memory/memories.jsonl``)::

    {"id": "<12-hex>", "ts": <epoch float>, "iso": "<local iso>",
     "content": "...", "tags": [...], "source": "session:<id>"}

Optional extra keys are added when present: ``source_rowid``,
``version``, ``supersedes`` (the export id of the superseded entry).
Consumers that only know the base shape can ignore them.

Only ``active`` entries are exported by default — quarantined and
retracted rows never leave the store unless ``include_non_active``
is requested explicitly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from devin_memory.store import Entry, MemoryStore


def _export_id(entry: Entry) -> str:
    """Stable 12-hex id derived from the row — same input, same id."""
    digest = hashlib.sha256(
        f"devin-memory:{entry.id}:{entry.created_at}".encode()
    ).hexdigest()
    return digest[:12]


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000).astimezone().strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )


def _to_line(entry: Entry, export_ids: dict[int, str]) -> dict:
    row: dict = {
        "id": export_ids[entry.id],
        "ts": entry.created_at / 1000,
        "iso": _iso(entry.created_at),
        "content": entry.content,
        "tags": list(entry.tags),
        "source": (
            f"session:{entry.source_session_id}"
            if entry.source_session_id
            else "devin-memory"
        ),
    }
    if entry.source_rowid is not None:
        row["source_rowid"] = entry.source_rowid
    if entry.version > 1:
        row["version"] = entry.version
    if entry.supersedes_id is not None:
        row["supersedes"] = export_ids.get(entry.supersedes_id)
    return row


def export_jsonl(
    store: MemoryStore,
    out: str | Path,
    *,
    include_non_active: bool = False,
) -> int:
    """Dump entries to ``out`` (one JSON object per line). Returns count."""
    entries = (
        store.entries()
        if include_non_active
        else store.entries(status="active")
    )
    # ids over *all* rows so `supersedes` chains resolve even when the
    # predecessor is retracted and therefore not exported itself
    export_ids = {e.id: _export_id(e) for e in store.entries()}
    lines = []
    for e in entries:
        row = _to_line(e, export_ids)
        if row.get("supersedes") is None:
            row.pop("supersedes", None)
        lines.append(json.dumps(row))
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)
