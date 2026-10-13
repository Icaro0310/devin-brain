"""weekly-report: public-safe aggregate, learning-weekly cursor, fail-open.

The weekly report is the PUBLIC surface of the learning loop: aggregate
counts, theme names and dates only — never session text, ids or paths.
"""

import json
import re
from pathlib import Path

import pytest
from conftest import (
    EXPECTED_LESSON_TEXTS,
    FAKE_API_KEY,
    FAKE_B64_BLOB,
    LESSON_SESSION_ID,
)

from devin_memory.learning import cli

CURSOR_NAME = "devin-learning-weekly-state.json"


@pytest.fixture()
def cursor_dir(tmp_path, monkeypatch):
    d = tmp_path / "cursor"
    monkeypatch.setenv("DEVIN_CURSOR_DIR", str(d))
    return d


def _weekly(db, out, *extra):
    return cli.main(
        ["weekly-report", "--sessions-db", str(db), "--out", str(out), *extra]
    )


def _report_file(out: Path) -> Path:
    files = list(out.glob("weekly-*.md"))
    assert len(files) == 1
    assert re.fullmatch(r"weekly-\d{4}-W\d{2}\.md", files[0].name)
    return files[0]


def test_weekly_writes_report_with_sections(sessions_db, tmp_path, cursor_dir):
    out = tmp_path / "reports"
    assert _weekly(sessions_db, out, "--since", "0") == 0
    md = _report_file(out).read_text(encoding="utf-8")
    assert md.startswith("# Weekly learning report")
    assert "## Lessons by theme" in md
    assert "## New skills promoted" in md
    assert "## Quarantined items pending review" in md
    assert "lesson candidates: 8" in md
    assert "learned-testing" in md
    assert (cursor_dir / CURSOR_NAME).is_file()


def test_weekly_report_is_public_safe(sessions_db, tmp_path, cursor_dir, capsys):
    out = tmp_path / "reports"
    assert _weekly(sessions_db, out, "--since", "0", "--json") == 0
    payload = capsys.readouterr().out
    blob = payload + _report_file(out).read_text(encoding="utf-8")
    # No absolute paths — above all, never the user's home.
    assert str(Path.home()) not in blob
    assert str(sessions_db) not in blob
    assert str(tmp_path) not in blob
    # No session identifiers or verbatim session content.
    assert LESSON_SESSION_ID not in blob
    for text in EXPECTED_LESSON_TEXTS:
        assert text not in blob
    assert FAKE_API_KEY not in blob
    assert FAKE_B64_BLOB not in blob


def test_weekly_second_run_reports_no_new(sessions_db, tmp_path, cursor_dir, capsys):
    out = tmp_path / "reports"
    assert _weekly(sessions_db, out, "--since", "0") == 0
    capsys.readouterr()
    # Second run resumes at the committed watermark → nothing new.
    assert _weekly(sessions_db, out) == 0
    assert "0 candidate(s)" in capsys.readouterr().out
    md = _report_file(out).read_text(encoding="utf-8")
    assert "lesson candidates: 0" in md
    assert md.count("_None this window._") == 3
    state = json.loads((cursor_dir / CURSOR_NAME).read_text(encoding="utf-8"))
    assert state["last_node_at"] > 0
    assert state["last_report_week"]


def test_weekly_corrupt_cursor_falls_back_to_window(
    sessions_db, tmp_path, cursor_dir
):
    cursor_dir.mkdir(parents=True)
    (cursor_dir / CURSOR_NAME).write_text("{not json!!", encoding="utf-8")
    out = tmp_path / "reports"
    # Corrupt state → fail-open to the --days window, no crash.
    assert _weekly(sessions_db, out, "--days", "365") == 0
    md = _report_file(out).read_text(encoding="utf-8")
    assert "lesson candidates: 8" in md
    # …and the cursor self-heals with a valid commit.
    state = json.loads((cursor_dir / CURSOR_NAME).read_text(encoding="utf-8"))
    assert state["last_node_at"] > 0


def test_weekly_cursor_dir_override(sessions_db, tmp_path, cursor_dir, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    out = tmp_path / "reports"
    assert _weekly(sessions_db, out, "--since", "0") == 0
    assert (cursor_dir / CURSOR_NAME).is_file()
    assert not (work / ".devin").exists()


def test_weekly_json_shape(sessions_db, tmp_path, cursor_dir, capsys):
    assert _weekly(sessions_db, tmp_path / "reports", "--since", "0", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool"] == "devin-learning"
    assert report["kind"] == "weekly-public-report"
    assert report["candidates"] == 8
    assert report["accepted"] == 4
    assert report["dropped"] == 4
    assert sum(report["themes"].values()) == 4
    assert {s["skill"] for s in report["skills"]} == {
        "learned-testing",
        "learned-git-workflow",
        "learned-security",
        "learned-docs",
    }
    assert sum(report["quarantine"].values()) >= 4


def test_weekly_missing_db_fails_cleanly(tmp_path, cursor_dir, capsys):
    rc = _weekly(tmp_path / "nope.db", tmp_path / "reports")
    assert rc == 3
    assert "nope.db" in capsys.readouterr().err
