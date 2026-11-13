"""``devin-memory ledger migrate`` — legacy ~/.devin/ledger import."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from devin_memory.ledger import Ledger, migrate, storage

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _legacy_dir(tmp_path: Path) -> Path:
    src = tmp_path / "legacy"
    src.mkdir()
    shutil.copy(FIXTURES / "legacy-ledger.jsonl", src / "ledger.jsonl")
    shutil.copy(FIXTURES / "legacy-sessions.jsonl", src / "sessions.jsonl")
    (src / "handoffs").mkdir()
    shutil.copy(FIXTURES / "legacy-handoffs" / "DL-c3d4.md",
                src / "handoffs" / "DL-c3d4.md")
    return src


def test_migrate_preserves_tasks_sessions_handoffs(tmp_path, monkeypatch):
    src = _legacy_dir(tmp_path)
    dst = tmp_path / "newstore"
    rep = migrate.migrate_legacy(src, dst)
    assert rep["tasks"] == 2
    assert rep["sessions"] == 2
    assert rep["handoffs"] == 1
    assert rep["to"] == str(dst)

    tasks = Ledger(dst).tasks()
    assert set(tasks) == {"DL-a1b2", "DL-c3d4"}
    assert tasks["DL-a1b2"]["status"] == "done"
    assert tasks["DL-c3d4"]["status"] == "parked"
    assert tasks["DL-c3d4"]["next"] == "resume at step 2"
    assert (dst / "handoffs" / "DL-c3d4.md").exists()
    assert (dst / "sessions.jsonl").exists()


def test_migrate_refuses_nonempty_destination(tmp_path):
    src = _legacy_dir(tmp_path)
    dst = tmp_path / "newstore"
    dst.mkdir()
    (dst / "ledger.jsonl").write_text('{"op":"add","id":"DL-ffff","title":"x","accept":["y"],"ts":"2026-01-01T00:00:00Z"}\n')
    with pytest.raises(migrate.MigrateError):
        migrate.migrate_legacy(src, dst)


def test_migrate_missing_source_ledger(tmp_path):
    with pytest.raises(migrate.MigrateError):
        migrate.migrate_legacy(tmp_path / "nope", tmp_path / "dst")


def test_migrate_via_cli(tmp_path, monkeypatch, capsys):
    from devin_memory.cli import main as cli_main
    src = _legacy_dir(tmp_path)
    monkeypatch.setenv("DEVIN_LEDGER_DIR", str(tmp_path / "newstore"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    # cli_main -> ledger cli -> migrate uses storage.ledger_dir() (env wins)
    rc = cli_main(["ledger", "migrate", "--from-dir", str(src)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"tasks": 2' in out
