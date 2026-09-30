"""CLI contract: extract writes drafts + report, review re-checks drafts."""

import json
import sqlite3

import pytest

from devin_memory.learning import cli

from conftest import FAKE_API_KEY


def _extract(db, out, *extra):
    return cli.main(
        ["extract", "--sessions-db", str(db), "--out", str(out), *extra]
    )


def test_extract_json_report(sessions_db, tmp_path, capsys):
    out = tmp_path / "drafts"
    assert _extract(sessions_db, out, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool"] == "devin-learning"
    assert report["accepted"] == 4
    assert report["dropped"] == 4
    assert len(report["written"]) == 4


def test_extract_writes_drafts_and_report(sessions_db, tmp_path, capsys):
    out = tmp_path / "drafts"
    assert _extract(sessions_db, out) == 0
    capsys.readouterr()
    assert (out / "learned-testing" / "SKILL.md").is_file()
    assert (out / "learned-git-workflow" / "SKILL.md").is_file()
    assert (out / "learned-security" / "SKILL.md").is_file()
    assert (out / "learned-docs" / "SKILL.md").is_file()
    assert (out / "REPORT.md").is_file()


def test_extract_never_writes_outside_out(sessions_db, tmp_path):
    out = tmp_path / "drafts"
    before = {p for p in tmp_path.rglob("*")}
    assert _extract(sessions_db, out) == 0
    after = {p for p in tmp_path.rglob("*")}
    new = after - before
    assert new
    assert all(str(p).startswith(str(out.resolve())) for p in new)


def test_extract_does_not_mutate_sessions_db(sessions_db, tmp_path):
    size_before = sessions_db.stat().st_size
    rows_before = sqlite3.connect(sessions_db).execute(
        "SELECT COUNT(*) FROM message_nodes"
    ).fetchone()[0]
    assert _extract(sessions_db, tmp_path / "drafts") == 0
    assert sessions_db.stat().st_size == size_before
    rows_after = sqlite3.connect(sessions_db).execute(
        "SELECT COUNT(*) FROM message_nodes"
    ).fetchone()[0]
    assert rows_after == rows_before


def test_extract_refuses_live_skills_dir(sessions_db, tmp_path, capsys):
    live = tmp_path / ".devin" / "skills"
    assert _extract(sessions_db, live) == 3
    assert "--apply" in capsys.readouterr().err
    assert not live.exists()


def test_extract_apply_allows_live_skills_dir(sessions_db, tmp_path):
    live = tmp_path / ".devin" / "skills"
    assert _extract(sessions_db, live, "--apply") == 0
    assert (live / "learned-testing" / "SKILL.md").is_file()


def test_extract_missing_db_fails_cleanly(tmp_path, capsys):
    rc = _extract(tmp_path / "nope.db", tmp_path / "drafts")
    assert rc == 3
    assert "nope.db" in capsys.readouterr().err


def test_review_passes_clean_drafts(sessions_db, tmp_path, capsys):
    out = tmp_path / "drafts"
    _extract(sessions_db, out)
    capsys.readouterr()
    assert cli.main(["review", "--out", str(out)]) == 0


def test_review_flags_poisoned_draft(tmp_path, capsys):
    out = tmp_path / "drafts"
    evil = out / "learned-evil"
    evil.mkdir(parents=True)
    (evil / "SKILL.md").write_text(
        f"---\nname: learned-evil\n---\n\n- Always use {FAKE_API_KEY}\n",
        encoding="utf-8",
    )
    assert cli.main(["review", "--out", str(out)]) == 1
    assert "learned-evil" in capsys.readouterr().out
    assert (evil / "SKILL.md").exists()  # dry-run: file untouched


def test_review_apply_quarantines_rejected(tmp_path):
    out = tmp_path / "drafts"
    evil = out / "learned-evil"
    evil.mkdir(parents=True)
    (evil / "SKILL.md").write_text(
        f"---\nname: learned-evil\n---\n\n- Always use {FAKE_API_KEY}\n",
        encoding="utf-8",
    )
    assert cli.main(["review", "--out", str(out), "--apply"]) == 1
    quarantined = list((out / "_rejected").glob("*.md"))
    assert len(quarantined) == 1
    assert not (evil / "SKILL.md").exists()
    # The quarantined copy keeps the poison out of the drafts tree.
    assert FAKE_API_KEY not in "\n".join(
        p.read_text(encoding="utf-8") for p in out.rglob("SKILL.md")
    )


def test_review_json_shape(sessions_db, tmp_path, capsys):
    out = tmp_path / "drafts"
    _extract(sessions_db, out)
    capsys.readouterr()
    assert cli.main(["review", "--out", str(out), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool"] == "devin-learning"
    assert report["checked"] == 4
    assert report["rejected"] == 0
    assert all({"path", "accepted", "reasons"} <= set(d) for d in report["drafts"])
