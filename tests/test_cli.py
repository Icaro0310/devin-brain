"""CLI tests: subcommands wired over a temp memory.db."""

from __future__ import annotations

import json

import pytest

from devin_memory.cli import main

from fixtures import CLEAN_FACT, SECRET_FACT, make_sessions_db


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "memory.db")


def test_retain_then_recall_json(db, capsys):
    assert main(["--db", db, "retain", CLEAN_FACT, "--tags", "a,b"]) == 0
    capsys.readouterr()

    assert main(["--db", db, "recall", "sessions", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["content"] == CLEAN_FACT
    assert rows[0]["tags"] == ["a", "b"]


def test_retain_secret_reports_quarantine(db, capsys):
    assert main(["--db", db, "retain", SECRET_FACT, "--json"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["status"] == "quarantined"
    assert entry["quarantine_reasons"]


def test_recall_text_output(db, capsys):
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert main(["--db", db, "recall", "sessions"]) == 0
    out = capsys.readouterr().out
    assert "ID" in out
    assert CLEAN_FACT[:10] in out


def test_quarantine_list_and_release(db, capsys):
    main(["--db", db, "retain", SECRET_FACT, "--json"])
    entry = json.loads(capsys.readouterr().out)

    assert main(["--db", db, "quarantine", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == [entry["id"]]

    assert main(["--db", db, "quarantine", "--release", str(entry["id"])]) == 0
    capsys.readouterr()
    assert main(["--db", db, "quarantine", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_retract_and_supersede_cli(db, capsys):
    main(["--db", db, "retain", "v1 fact", "--json"])
    entry = json.loads(capsys.readouterr().out)

    assert (
        main(["--db", db, "supersede", str(entry["id"]), "v2 fact", "--json"])
        == 0
    )
    new = json.loads(capsys.readouterr().out)
    assert new["version"] == 2

    assert main(["--db", db, "retract", str(new["id"])]) == 0
    capsys.readouterr()
    assert main(["--db", db, "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["status"] for r in rows} == {"retracted"}


def test_export_cli(db, tmp_path, capsys):
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    out = tmp_path / "memories.jsonl"
    assert main(["--db", db, "export", "--out", str(out)]) == 0
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows[0]["content"] == CLEAN_FACT


def test_verify_cli(db, tmp_path, capsys):
    sessions_db, session_id, rowid = make_sessions_db(tmp_path)
    main(
        [
            "--db", db, "retain", CLEAN_FACT,
            "--source-session", session_id,
            "--source-rowid", str(rowid),
        ]
    )
    capsys.readouterr()
    main(["--db", db, "list", "--json"])
    entry = json.loads(capsys.readouterr().out)[0]

    assert (
        main(
            ["--db", db, "verify", str(entry["id"]),
             "--sessions-db", str(sessions_db)]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["session_found"] is True
    assert report["rowid_found"] is True


def test_verify_cli_fails_on_bad_session(db, tmp_path, capsys):
    sessions_db, _, _ = make_sessions_db(tmp_path)
    main(
        ["--db", db, "retain", CLEAN_FACT,
         "--source-session", "no-such-session"]
    )
    capsys.readouterr()
    main(["--db", db, "list", "--json"])
    entry = json.loads(capsys.readouterr().out)[0]
    rc = main(
        ["--db", db, "verify", str(entry["id"]),
         "--sessions-db", str(sessions_db)]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["session_found"] is False
    assert rc == 1


def test_env_var_db_default(tmp_path, monkeypatch, capsys):
    db = tmp_path / "env.db"
    monkeypatch.setenv("DEVIN_MEMORY_DB", str(db))
    monkeypatch.chdir(tmp_path)
    assert main(["retain", CLEAN_FACT]) == 0
    assert db.is_file()
