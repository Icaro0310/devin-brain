"""Dispatch contract: ``devin-memory ledger`` domain + memory compat."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from devin_memory.cli import main as cli_main
from devin_memory.ledger import storage


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    monkeypatch.setenv("DEVIN_LEDGER_DIR", str(d))
    return d


def test_ledger_init_creates_layout(ledger_env, capsys):
    assert cli_main(["ledger", "init"]) == 0
    assert (ledger_env / "ledger.jsonl").parent == ledger_env
    assert (ledger_env / "handoffs").is_dir()
    assert "ledger dir:" in capsys.readouterr().out


def test_ledger_add_list_roundtrip(ledger_env, capsys):
    assert cli_main(["ledger", "add", "dispatch task", "--accept", "rc=0"]) == 0
    tid = capsys.readouterr().out.strip()
    assert tid.startswith("DL-")
    assert cli_main(["ledger", "list"]) == 0
    assert "dispatch task" in capsys.readouterr().out


def test_ledger_hook_session_end_records(ledger_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"session_id": "sess-dispatch", "event": "end"})))
    assert cli_main(["ledger", "hook", "session-end"]) == 0
    lines = (ledger_env / "sessions.jsonl").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["session_id"] == "sess-dispatch"
    assert rec["event"] == "end"


def test_ledger_stats_empty_store(ledger_env, capsys):
    assert cli_main(["ledger", "stats"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["total_tasks"] == 0
    assert rep["ledger_exists"] is False


def test_memory_parser_still_receives_non_ledger_argv(ledger_env):
    # 'bogus' is not a ledger command -> must reach the memory parser,
    # which rejects it via argparse SystemExit(2). Proves the 'ledger'
    # prefix is the only dispatch boundary.
    with pytest.raises(SystemExit) as ei:
        cli_main(["bogus-domain-command"])
    assert ei.value.code == 2


def test_memory_help_still_works(ledger_env):
    with pytest.raises(SystemExit) as ei:
        cli_main(["--help"])
    assert ei.value.code == 0


def test_module_entry_point(ledger_env, capsys):
    from devin_memory.ledger import __main__  # noqa: F401 — importable
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "devin_memory.ledger", "stats"],
        capture_output=True, text=True,
        env={"DEVIN_LEDGER_DIR": str(ledger_env), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert '"total_tasks"' in r.stdout or "total_tasks" in r.stdout
