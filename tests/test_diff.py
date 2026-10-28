"""``devin-memory diff A.db B.db`` — read-only store divergence by id.

Fixtures copy a store file before mutating one side, because the diff is
keyed by the export id (row id + created_at) — only rows that share
their origin can ever match.
"""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest
from devin_memory import ops
from devin_memory.cli import main
from devin_memory.diff import diff_stores
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, CLEAN_FACT_2, SECRET_FACT


def _mkdb(path, *contents):
    """Create a store with one active entry per content string."""
    with MemoryStore(path) as s:
        for c in contents:
            ops.retain(s, c)
    return path


@pytest.fixture
def pair(tmp_path):
    """Two identical store files: base.db + a copy."""
    base = _mkdb(tmp_path / "a.db", CLEAN_FACT, CLEAN_FACT_2)
    other = tmp_path / "b.db"
    shutil.copy(base, other)
    return base, other


# ---------------------------------------------------------------------------
# pure-function level
# ---------------------------------------------------------------------------


def test_identical_stores(pair):
    a, b = pair
    report = diff_stores(a, b)
    assert report["different"] is False
    assert report["added"] == report["removed"] == report["changed"] == []
    assert report["a_entries"] == 2


def test_added_entry(pair):
    a, b = pair
    with MemoryStore(b) as s:
        ops.retain(s, "only in B")
    report = diff_stores(a, b)
    assert report["different"] is True
    assert [i["row"]["content"] for i in report["added"]] == ["only in B"]
    assert report["removed"] == []


def test_retracted_entry_is_removed(pair):
    """A retracted row leaves the active export → shows as removed."""
    a, b = pair
    with MemoryStore(b) as s:
        entry = s.entries(status="active")[0]
        ops.retract(s, entry.id)
    report = diff_stores(a, b)
    assert len(report["removed"]) == 1


def test_content_edit_is_changed(pair, tmp_path):
    a, b = pair
    con = sqlite3.connect(b)
    con.execute(
        "UPDATE entries SET content = ? WHERE content = ?",
        ("edited fact", CLEAN_FACT),
    )
    con.commit()
    con.close()
    report = diff_stores(a, b)
    assert len(report["changed"]) == 1
    fields = report["changed"][0]["fields"]
    assert fields["content"] == {"a": CLEAN_FACT, "b": "edited fact"}


def test_all_flag_reports_status_change(pair):
    """With --all a retraction is a status change, not a removal."""
    a, b = pair
    with MemoryStore(b) as s:
        entry = s.entries(status="active")[0]
        ops.retract(s, entry.id)
    report = diff_stores(a, b, include_non_active=True)
    assert report["removed"] == []
    assert len(report["changed"]) == 1
    fields = report["changed"][0]["fields"]
    assert fields["status"] == {"a": "active", "b": "retracted"}


def test_quarantined_excluded_by_default(pair):
    a, b = pair
    with MemoryStore(b) as s:
        ops.retain(s, SECRET_FACT)  # quarantined at retain time
    report = diff_stores(a, b)
    assert report["different"] is False
    full = diff_stores(a, b, include_non_active=True)
    assert len(full["added"]) == 1


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_cli_identical_exit_0(pair, capsys):
    a, b = pair
    assert main(["diff", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "result: IDENTICAL" in out
    assert "(none)" in out


def test_cli_divergence_exit_1_and_lists_ids(pair, capsys):
    a, b = pair
    with MemoryStore(b) as s:
        ops.retain(s, "only in B")
    assert main(["diff", str(a), str(b)]) == 1
    out = capsys.readouterr().out
    assert "added in B (1)" in out
    assert "only in B" in out
    assert "result: DIFFERENT" in out


def test_cli_json_shape(pair, capsys):
    a, b = pair
    with MemoryStore(b) as s:
        ops.retain(s, "only in B")
    assert main(["diff", str(a), str(b), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["different"] is True
    assert [i["row"]["content"] for i in report["added"]] == ["only in B"]


def test_cli_missing_db_exit_2(tmp_path, pair, capsys):
    a, _ = pair
    missing = tmp_path / "nope.db"
    assert main(["diff", str(a), str(missing)]) == 2
    assert "no such file" in capsys.readouterr().err
    # and the missing file was not created by the read attempt
    assert not missing.exists()


def test_cli_not_a_memory_db_exit_2(tmp_path, pair, capsys):
    a, _ = pair
    junk = tmp_path / "junk.db"
    sqlite3.connect(junk).close()  # valid sqlite, no entries table
    assert main(["diff", str(a), str(junk)]) == 2
    assert "cannot read" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# read-only guarantee
# ---------------------------------------------------------------------------


def test_diff_never_writes(pair):
    """Neither db file, nor journal/wal siblings, change under diff."""
    a, b = pair
    before_a = a.read_bytes()
    before_b = b.read_bytes()
    main(["diff", str(a), str(b)])
    assert a.read_bytes() == before_a
    assert b.read_bytes() == before_b
    assert list(a.parent.glob("*.db-*")) == []
