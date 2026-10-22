"""``--since`` filter tests: parse grammar, query-layer cutoff, and the
CLI/MCP surfaces that expose it.

Entry age is backdated with a plain SQL UPDATE on ``created_at`` — the
same trick ``test_expiry.py`` uses, since the public API always stamps
``created_at = now`` on write.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import devin_memory.mcp_server as mcp_srv
from devin_memory import ops
from devin_memory.cli import main
from devin_memory.export import export_jsonl
from devin_memory.store import MemoryStore, parse_since

from fixtures import CLEAN_FACT, CLEAN_FACT_2

NOW_MS = 1_800_000_000_000  # fixed reference for parse tests


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def store(db_path):
    with MemoryStore(db_path) as s:
        yield s


def _age_days(path: Path, entry_id: int, days: float) -> None:
    backdated = int((time.time() - days * 86400) * 1000)
    con = sqlite3.connect(path)
    try:
        with con:
            con.execute(
                "UPDATE entries SET created_at = ? WHERE id = ?",
                (backdated, entry_id),
            )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec,expected_ms",
    [
        ("30s", 30_000),
        ("15m", 900_000),
        ("24h", 86_400_000),
        ("7d", 604_800_000),
        ("2w", 1_209_600_000),
        ("7D", 604_800_000),  # case-insensitive
        (" 24h ", 86_400_000),  # whitespace-tolerant
    ],
)
def test_parse_since_relative(spec, expected_ms):
    assert parse_since(spec, now_ms=NOW_MS) == NOW_MS - expected_ms


def test_parse_since_iso_date_and_datetime():
    # ISO forms go through parse_expires_at: naive means UTC.
    midnight = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000
    noon = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).timestamp() * 1000
    assert parse_since("2026-10-01", now_ms=NOW_MS) == midnight
    assert parse_since("2026-10-01T12:00:00Z", now_ms=NOW_MS) == noon


@pytest.mark.parametrize("bad", ["", "  ", "yesterday", "7x", "h", "-7d",
                                 "2026-13-40", "0"])
def test_parse_since_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_since(bad, now_ms=NOW_MS)


def test_parse_since_rejects_non_string():
    with pytest.raises(ValueError):
        parse_since(None, now_ms=NOW_MS)


# ---------------------------------------------------------------------------
# query layer
# ---------------------------------------------------------------------------


def test_entries_since_filters_backdated(store, db_path):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.retain(store, CLEAN_FACT_2)
    _age_days(db_path, old.id, 10)

    cutoff = time.time() * 1000 - 5 * 86_400_000  # 5d ago
    ids = [e.id for e in store.entries(since=cutoff)]
    assert ids == [new.id]


def test_entries_since_combines_with_status(store, db_path):
    old = ops.retain(store, CLEAN_FACT)
    ops.retain(store, "quota note", tags=["q"])
    _age_days(db_path, old.id, 30)
    cutoff = time.time() * 1000 - 5 * 86_400_000
    recent = store.entries(status="active", since=cutoff)
    assert [e.content for e in recent] == ["quota note"]


def test_list_entries_passes_since(store, db_path):
    old = ops.retain(store, CLEAN_FACT)
    _age_days(db_path, old.id, 10)
    cutoff = time.time() * 1000 - 5 * 86_400_000
    assert ops.list_entries(store, since=cutoff) == []


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_since_skips_old_rows(store, db_path, tmp_path):
    old = ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT_2)
    _age_days(db_path, old.id, 10)
    out = tmp_path / "memories.jsonl"
    cutoff = time.time() * 1000 - 5 * 86_400_000
    n = export_jsonl(store, out, since=cutoff)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert n == 1
    assert rows[0]["content"] == CLEAN_FACT_2


def test_export_since_still_anchors_supersedes_ids(store, db_path, tmp_path):
    """The export-id map is built over *all* rows so a since-filtered
    export can still resolve a supersedes chain to an old predecessor."""
    old = ops.retain(store, "v1 fact")
    new = ops.supersede(store, old.id, "v2 fact")
    _age_days(db_path, old.id, 30)
    out = tmp_path / "memories.jsonl"
    cutoff = time.time() * 1000 - 5 * 86_400_000
    n = export_jsonl(store, out, since=cutoff)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert n == 1
    assert rows[0]["content"] == "v2 fact"
    assert rows[0]["supersedes"] is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "memory.db")


def _cli_seed(db, capsys):
    main(["--db", db, "retain", CLEAN_FACT])
    main(["--db", db, "retain", CLEAN_FACT_2])
    capsys.readouterr()
    return Path(db)


def test_cli_list_since(db, capsys):
    path = _cli_seed(db, capsys)
    # Backdate every row to 2015 — inside a "since 2000" window but far
    # outside a 7d one.
    con = sqlite3.connect(path)
    with con:
        con.execute("UPDATE entries SET created_at = 1420070400000")
    con.close()
    assert main(["--db", db, "list", "--since", "7d", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["--db", db, "list", "--since", "2000-01-01",
                 "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_cli_export_since(db, tmp_path, capsys):
    path = _cli_seed(db, capsys)
    con = sqlite3.connect(path)
    with con:
        con.execute("UPDATE entries SET created_at = 1420070400000")
    con.close()
    out = tmp_path / "memories.jsonl"
    assert (
        main(["--db", db, "export", "--out", str(out), "--since", "7d"])
        == 0
    )
    assert "exported 0 entries" in capsys.readouterr().out
    assert out.read_text() == ""


@pytest.mark.parametrize("sub", ["list", "export"])
def test_cli_since_rejects_garbage(db, tmp_path, capsys, sub):
    argv = ["--db", db, sub, "--since", "not-a-date"]
    if sub == "export":
        argv += ["--out", str(tmp_path / "m.jsonl")]
    assert main(argv) == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "memory.db"
    monkeypatch.setattr(mcp_srv, "_DB_PATH", str(db_file))
    return db_file


def test_mcp_list_since(mcp_db):
    old = mcp_srv.do_retain(CLEAN_FACT)
    mcp_srv.do_retain(CLEAN_FACT_2)
    _age_days(mcp_db, old["id"], 10)
    rows = mcp_srv.do_list(since="7d")
    assert [r["content"] for r in rows] == [CLEAN_FACT_2]
    assert mcp_srv.do_list(since="1h") == rows


def test_mcp_list_since_bad_value_is_an_error(mcp_db):
    # do_* raise through (only the tool wrapper guards); the CLI prints
    # the same ValueError. Keep both surfaces honest.
    with pytest.raises(ValueError):
        mcp_srv.do_list(since="banana")
