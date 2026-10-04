"""MM-1 tests: ``devin-memory extract`` mines one session into proposed
entries — screened, deduplicated, inactive until approved."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from devin_internals.fixtures import create_sessions_db

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

SESSION_ID = "fixture-extract-session"
WORKSPACE = "/fixture/workspace/extract"
BASE_TS_MS = 1_790_640_000_000

FAKE_KEY = "sk-" + "FAKE" * 8

# (role, text) — one message_nodes row per entry.
MESSAGES: list[tuple[str, str]] = [
    ("user", "na verdade the right way is `pytest -q`, not the full suite."),
    ("user", "Sempre rode os testes antes de commitar."),
    ("user", "can you check why the build is red?"),
    ("assistant", "The fix is to run `git rebase main` before merging."),
    ("user", "the config lives at /home/devin/app/config.yaml."),
    ("user", f"Never share this key {FAKE_KEY} anywhere."),
    ("agent", "Done — summary posted."),
]


def build_db(path: Path) -> Path:
    db = create_sessions_db(path, n_sessions=1)
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "INSERT INTO sessions(id, working_directory, backend_type, model,"
            " agent_mode, created_at, last_activity_at, title, main_chain_id,"
            " shell_last_seen_index, cogs_json, workspace_dirs, hidden,"
            " metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                SESSION_ID,
                WORKSPACE,
                "fixture-backend",
                "fixture-model",
                "fixture-mode",
                BASE_TS_MS,
                BASE_TS_MS + 9_999_999_000,  # most recent activity wins
                "Fixture extract session",
                1,
                0,
                json.dumps({"synthetic": True}),
                json.dumps([WORKSPACE]),
                0,
                json.dumps({"synthetic": True}),
            ),
        )
        for node_id, (role, text) in enumerate(MESSAGES, start=1):
            con.execute(
                "INSERT INTO message_nodes(session_id, node_id,"
                " parent_node_id, chat_message, created_at, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    SESSION_ID,
                    node_id,
                    None if node_id == 1 else node_id - 1,
                    json.dumps({"role": role, "text": text}),
                    BASE_TS_MS + node_id * 10_000,
                    json.dumps({"synthetic": True}),
                ),
            )
    con.close()
    return db


@pytest.fixture
def sessions_db(tmp_path):
    return build_db(tmp_path / "sessions.db")


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# ops-level extraction
# ---------------------------------------------------------------------------


def test_extract_stores_candidates_as_proposed(store, sessions_db):
    report = ops.extract_session(
        store, sessions_db, session_id=SESSION_ID
    )
    assert report["session_id"] == SESSION_ID
    statuses = [i["status"] for i in report["items"]]
    assert statuses.count("proposed") >= 4  # correction+pref+command+path
    assert "quarantined" in statuses  # the secret-bearing sentence
    # proposed entries are invisible to recall
    proposed = [i for i in report["items"] if i["status"] == "proposed"]
    first = store.get(proposed[0]["id"])
    assert first.status == "proposed"
    assert ops.recall(store, "") == []


def test_extract_records_signal_tags_and_provenance(store, sessions_db):
    report = ops.extract_session(
        store, sessions_db, session_id=SESSION_ID
    )
    by_id = {i["id"]: i for i in report["items"]}
    entries = {i["id"]: store.get(i["id"]) for i in report["items"]}
    kinds = {s for i in report["items"] for s in i["signals"]}
    assert {"correction", "preference", "command", "path"} <= kinds
    for entry in entries.values():
        assert entry.source_session_id == SESSION_ID
        assert entry.source_rowid is not None
        assert entry.workspace == WORKSPACE
        assert "extracted" in entry.tags
    for item in report["items"]:
        for sig in item["signals"]:
            assert f"signal-{sig}" in entries[item["id"]].tags


def test_extract_auto_approve_stores_active(store, sessions_db):
    ops.extract_session(
        store, sessions_db, session_id=SESSION_ID, auto_approve=True
    )
    statuses = {e.status for e in store.entries()}
    assert "active" in statuses
    assert "proposed" not in statuses


def test_extract_is_idempotent(store, sessions_db):
    ops.extract_session(store, sessions_db, session_id=SESSION_ID)
    report = ops.extract_session(
        store, sessions_db, session_id=SESSION_ID
    )
    assert report["items"] == []
    assert report["skipped_duplicates"] == report["candidates"] > 0


def test_extract_latest_resolves_most_recent_session(store, sessions_db):
    report = ops.extract_session(store, sessions_db, latest=True)
    assert report["session_id"] == SESSION_ID  # newest last_activity_at


def test_extract_requires_session_or_latest(store, sessions_db):
    with pytest.raises(ops.MemoryOpsError):
        ops.extract_session(store, sessions_db)


def test_approve_promotes_proposed_to_active(store, sessions_db):
    report = ops.extract_session(
        store, sessions_db, session_id=SESSION_ID
    )
    pid = next(i["id"] for i in report["items"]
               if i["status"] == "proposed")
    entry = ops.approve(store, pid)
    assert entry.status == "active"
    assert entry in ops.recall(store, "")


def test_approve_rejects_non_proposed(store):
    e = ops.retain(store, "a normal fact")
    with pytest.raises(ops.InvalidTransitionError):
        ops.approve(store, e.id)


# ---------------------------------------------------------------------------
# CLI surface — and secrets never reach stdout
# ---------------------------------------------------------------------------


def test_cli_extract_end_to_end(tmp_path, sessions_db, capsys):
    db = str(tmp_path / "memory.db")
    rc = main(
        [
            "--db", db, "extract", SESSION_ID,
            "--sessions-db", str(sessions_db),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "proposed=" in out
    assert FAKE_KEY not in out  # secret values never printed


def test_cli_extract_json_has_no_content(tmp_path, sessions_db, capsys):
    db = str(tmp_path / "memory.db")
    rc = main(
        [
            "--db", db, "extract", "--latest",
            "--sessions-db", str(sessions_db), "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["session_id"] == SESSION_ID
    assert all("content" not in item for item in report["items"])
    assert FAKE_KEY not in out


def test_cli_approve_then_recall(tmp_path, sessions_db, capsys):
    db = str(tmp_path / "memory.db")
    main(
        [
            "--db", db, "extract", SESSION_ID,
            "--sessions-db", str(sessions_db), "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    pid = next(i["id"] for i in report["items"]
               if i["status"] == "proposed")

    assert main(["--db", db, "approve", str(pid)]) == 0
    capsys.readouterr()
    assert main(["--db", db, "list", "--status", "proposed",
                 "--json"]) == 0
    remaining = json.loads(capsys.readouterr().out)
    assert all(r["id"] != pid for r in remaining)

    assert main(["--db", db, "recall", "", "--json"]) == 0
    active = json.loads(capsys.readouterr().out)
    assert any(r["id"] == pid for r in active)
