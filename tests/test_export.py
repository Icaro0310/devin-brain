"""Export tests: memories.jsonl in the memory-MCP line shape."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from devin_memory import ops
from devin_memory.export import export_jsonl
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, SECRET_FACT


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_export_writes_memory_mcp_shape(store, tmp_path):
    ops.retain(store, CLEAN_FACT, tags=["a", "b"], source_session_id="sess-1")
    out = tmp_path / "memories.jsonl"
    n = export_jsonl(store, out)
    assert n == 1

    (row,) = _lines(out)
    assert set(row) >= {"id", "ts", "iso", "content", "tags", "source"}
    assert row["content"] == CLEAN_FACT
    assert row["tags"] == ["a", "b"]
    assert row["source"] == "session:sess-1"
    assert isinstance(row["ts"], float)
    # ISO-8601 with numeric offset, e.g. 2026-09-29T15:46:14+0100
    datetime.strptime(row["iso"], "%Y-%m-%dT%H:%M:%S%z")


def test_export_excludes_non_active_by_default(store, tmp_path):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, SECRET_FACT)  # quarantined
    e = ops.retain(store, "old fact")
    ops.retract(store, e.id)

    out = tmp_path / "memories.jsonl"
    assert export_jsonl(store, out) == 1
    assert [r["content"] for r in _lines(out)] == [CLEAN_FACT]


def test_export_ids_are_stable_across_runs(store, tmp_path):
    ops.retain(store, CLEAN_FACT)
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    export_jsonl(store, first)
    export_jsonl(store, second)
    assert first.read_text() == second.read_text()


def test_export_carries_provenance(store, tmp_path):
    ops.retain(
        store, CLEAN_FACT, source_session_id="sess-1", source_rowid=9
    )
    out = tmp_path / "memories.jsonl"
    export_jsonl(store, out)
    (row,) = _lines(out)
    assert row["source_rowid"] == 9


def test_export_marks_superseded_chain(store, tmp_path):
    old = ops.retain(store, "v1")
    ops.supersede(store, old.id, "v2")
    out = tmp_path / "memories.jsonl"
    export_jsonl(store, out, include_non_active=True)
    rows = {r["content"]: r for r in _lines(out)}
    assert rows["v2"]["version"] == 2
    assert rows["v2"]["supersedes"] == rows["v1"]["id"]


def test_export_empty_store(store, tmp_path):
    out = tmp_path / "memories.jsonl"
    assert export_jsonl(store, out) == 0
    assert out.read_text() == ""
