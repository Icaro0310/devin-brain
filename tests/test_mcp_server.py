"""MCP server surface — the do_* ops work without the mcp package; the
server builder only runs when the optional `mcp` extra is installed."""

from __future__ import annotations

import importlib
import sys

import pytest

import devin_memory.mcp_server as mcp_srv


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr(mcp_srv, "_DB_PATH", str(db_path))
    return db_path


def test_retain_and_recall(db):
    out = mcp_srv.do_retain("pytest needs -k to filter tests", tags="qa")
    assert out["status"] == "active"
    hits = mcp_srv.do_recall("filter tests")
    assert hits and hits[0]["id"] == out["id"]


def test_screen_dry_run_does_not_write(db):
    poisoned = mcp_srv.do_screen("api_key=AKIA" + "A" * 16)
    clean = mcp_srv.do_screen("a normal memory")
    assert clean["status"] == "active"
    assert mcp_srv.do_list() == []  # screen never writes
    if poisoned["status"] == "quarantined":
        assert poisoned["reasons"]


def test_retain_quarantined_entry_not_recalled(db):
    mcp_srv.do_retain("OPENAI_API_KEY=sk-" + "x" * 40)
    assert mcp_srv.do_recall("OPENAI_API_KEY") == []
    quarantined = mcp_srv.do_list(status="quarantined")
    assert len(quarantined) == 1


def test_release_and_retract_lifecycle(db):
    entry = mcp_srv.do_retain("sk-live-" + "a" * 30)
    if entry["status"] == "quarantined":
        released = mcp_srv.do_release(entry["id"])
        assert released["status"] == "active"
    retracted = mcp_srv.do_retract(entry["id"])
    assert retracted["status"] == "retracted"
    assert mcp_srv.do_recall("sk-live") == []


def test_supersede_bumps_version(db):
    old = mcp_srv.do_retain("tests live in tests/")
    new = mcp_srv.do_supersede(old["id"], "tests live in test/")
    assert new["status"] == "active"
    assert new["supersedes_id"] == old["id"]


def test_unknown_entry_errors(db):
    with pytest.raises(Exception):
        mcp_srv.do_retract(999)


def test_tags_accept_list_and_csv(db):
    a = mcp_srv.do_retain("alpha fact", tags="one,two")
    b = mcp_srv.do_retain("beta fact", tags=["two", "three"])
    assert set(a["tags"]) == {"one", "two"}
    assert set(b["tags"]) == {"two", "three"}
    assert len(mcp_srv.do_recall("", tags="three")) == 1


def test_prime_returns_bounded_text(db):
    mcp_srv.do_retain("remember this for prime")
    out = mcp_srv.do_prime(max_tokens=200)
    assert "remember this for prime" in out["text"]


def test_build_server_registers_tools():
    mcp = pytest.importorskip("mcp")
    server = mcp_srv.build_server()
    manager = getattr(server, "_tool_manager", None)
    names = set(getattr(manager, "_tools", {}) or {})
    expected = {"retain", "recall", "screen", "list", "retract",
                "supersede", "quarantine", "release", "approve",
                "conflicts", "prime", "verify", "extract"}
    assert expected <= names
