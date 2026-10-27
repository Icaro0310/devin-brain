"""Held supersessions: a quarantined replacement no longer retires the
superseded memory — the old version stays ``active`` (and verifiable)
until review resolves the supersession.

- ``supersede`` → quarantined replacement: supersession held open
- ``quarantine --release`` on the successor: supersession applies
- ``retract`` on the successor: supersession rejected, old stays live
- ``quarantine <id> --hold-supersede``: after-the-fact hold — the
  already-retired parent returns to ``active`` while the successor is
  reviewed (also repairs pre-fix ≤0.3.1 rows)
"""

from __future__ import annotations

import json

import pytest

import devin_memory.mcp_server as mcp_srv
from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, SECRET_FACT


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# write-time hold: supersede screens the replacement into quarantine
# ---------------------------------------------------------------------------


def test_quarantined_supersession_holds_old_active(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)

    assert new.status == "quarantined"
    assert new.supersedes_id == old.id
    # the P0 fix: the superseded memory is NOT retired while its
    # replacement sits in quarantine
    assert store.get(old.id).status == "active"
    # recall keeps serving the old version — the hold leaves no gap
    assert [e.id for e in ops.recall(store, "")] == [old.id]


def test_release_held_supersession_applies_it(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)

    out = ops.release(store, new.id)
    assert out.status == "active"
    # releasing the replacement completes the supersession it held
    assert store.get(old.id).status == "retracted"
    assert [e.id for e in ops.recall(store, "")] == [new.id]


def test_reject_held_supersession_keeps_old(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)

    ops.retract(store, new.id)  # reviewer rejects the replacement
    assert store.get(new.id).status == "retracted"
    # the old memory was never retired — nothing to recover
    assert store.get(old.id).status == "active"
    assert [e.id for e in ops.recall(store, "")] == [old.id]


def test_supersede_blocked_while_hold_pending(store):
    old = ops.retain(store, CLEAN_FACT)
    pending = ops.supersede(store, old.id, SECRET_FACT)
    with pytest.raises(ops.InvalidTransitionError):
        ops.supersede(store, old.id, "another candidate v2")
    # resolving the pending successor unblocks the chain
    ops.retract(store, pending.id)
    new = ops.supersede(store, old.id, "another candidate v2")
    assert new.status == "active"


def test_retracting_held_parent_is_not_revived_by_release(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)
    ops.retract(store, old.id)  # reviewer kills the old version outright
    ops.release(store, new.id)
    assert store.get(new.id).status == "active"
    # release retires only an *active* parent — it never resurrects one
    assert store.get(old.id).status == "retracted"


# ---------------------------------------------------------------------------
# after-the-fact hold: quarantine <id> --hold-supersede
# ---------------------------------------------------------------------------


def test_hold_supersede_restores_retired_parent(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")  # clean: applied
    assert store.get(old.id).status == "retracted"

    out = ops.quarantine_entry(store, new.id, hold_supersede=True)
    assert out.status == "quarantined"
    # the supersession is held: the previous valid memory is back
    assert store.get(old.id).status == "active"
    assert [e.id for e in ops.recall(store, "")] == [old.id]


def test_hold_supersede_then_release_completes_supersession(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    ops.quarantine_entry(store, new.id, hold_supersede=True)

    ops.release(store, new.id)
    assert store.get(new.id).status == "active"
    assert store.get(old.id).status == "retracted"
    assert [e.id for e in ops.recall(store, "")] == [new.id]


def test_hold_supersede_then_reject_recovers_old(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    ops.quarantine_entry(store, new.id, hold_supersede=True)

    ops.retract(store, new.id)  # replacement rejected — recovery
    assert store.get(old.id).status == "active"
    assert [e.id for e in ops.recall(store, "")] == [old.id]


def test_hold_supersede_repairs_legacy_quarantined_pair(store):
    """Rows written by ≤0.3.1 can hold the buggy shape — successor
    quarantined, parent already retracted. The flag repairs them."""
    old = ops.retain(store, CLEAN_FACT)
    # simulate the pre-fix write path directly at store level
    new = store.supersede(
        old.id,
        SECRET_FACT,
        status="quarantined",
        quarantine_reasons=["secret:aws_access_key_id"],
    )
    assert store.get(old.id).status == "retracted"  # the old bug

    out = ops.quarantine_entry(store, new.id, hold_supersede=True)
    assert out.status == "quarantined"
    assert store.get(old.id).status == "active"


def test_hold_supersede_on_non_successor_raises(store):
    e = ops.retain(store, CLEAN_FACT)
    with pytest.raises(ops.InvalidTransitionError):
        ops.quarantine_entry(store, e.id, hold_supersede=True)
    # failed validation left the entry untouched
    assert store.get(e.id).status == "active"


def test_hold_supersede_on_retracted_raises(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    ops.retract(store, new.id)
    with pytest.raises(ops.InvalidTransitionError):
        ops.quarantine_entry(store, new.id, hold_supersede=True)


def test_quarantine_without_hold_keeps_parent_retracted(store):
    """Plain quarantine never rewrites history — only the flag holds."""
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    ops.quarantine_entry(store, new.id)
    assert store.get(new.id).status == "quarantined"
    assert store.get(old.id).status == "retracted"


def test_hold_supersede_leaves_under_review_parent_alone(store):
    """A parent that is itself quarantined is never promoted out of
    review by a hold on its successor."""
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, "schema is v17")
    store.set_status(old.id, "quarantined")  # parent's own review open
    ops.quarantine_entry(store, new.id, hold_supersede=True)
    assert store.get(new.id).status == "quarantined"
    assert store.get(old.id).status == "quarantined"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_quarantined_supersede_keeps_old_listed_active(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT, "--json"])
    old = json.loads(capsys.readouterr().out)

    assert (
        main(["--db", db, "supersede", str(old["id"]), SECRET_FACT,
              "--json"])
        == 0
    )
    new = json.loads(capsys.readouterr().out)
    assert new["status"] == "quarantined"

    main(["--db", db, "list", "--json"])
    rows = {r["id"]: r["status"] for r in json.loads(capsys.readouterr().out)}
    assert rows[old["id"]] == "active"
    assert rows[new["id"]] == "quarantined"

    assert (
        main(["--db", db, "quarantine", "--release", str(new["id"])]) == 0
    )
    capsys.readouterr()
    main(["--db", db, "list", "--json"])
    rows = {r["id"]: r["status"] for r in json.loads(capsys.readouterr().out)}
    assert rows[old["id"]] == "retracted"
    assert rows[new["id"]] == "active"


def test_cli_hold_supersede_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT, "--json"])
    old = json.loads(capsys.readouterr().out)
    main(["--db", db, "supersede", str(old["id"]), "schema is v17", "--json"])
    new = json.loads(capsys.readouterr().out)

    assert (
        main(
            ["--db", db, "quarantine", str(new["id"]), "--hold-supersede"]
        )
        == 0
    )
    assert "status=quarantined" in capsys.readouterr().out
    main(["--db", db, "list", "--json"])
    rows = {r["id"]: r["status"] for r in json.loads(capsys.readouterr().out)}
    assert rows[old["id"]] == "active"
    assert rows[new["id"]] == "quarantined"


def test_cli_hold_supersede_needs_an_id(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert main(["--db", db, "quarantine", "--hold-supersede"]) == 1
    assert "--hold-supersede needs an entry id" in capsys.readouterr().err


def test_cli_hold_supersede_rejected_with_release(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert (
        main(["--db", db, "quarantine", "--release", "1", "--hold-supersede"])
        == 1
    )
    assert "not with --release" in capsys.readouterr().err


def test_cli_hold_supersede_rejected_with_digest(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert main(["--db", db, "quarantine", "--digest", "--hold-supersede"]) == 1
    assert "read-only" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# MCP surface (do_* run without the mcp package)
# ---------------------------------------------------------------------------


def test_mcp_do_quarantine_hold_supersede(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_srv, "_DB_PATH", str(tmp_path / "memory.db"))
    old = mcp_srv.do_retain(CLEAN_FACT)
    new = mcp_srv.do_supersede(old["id"], "schema is v17")

    out = mcp_srv.do_quarantine(new["id"], hold_supersede=True)
    assert out["status"] == "quarantined"
    parent = mcp_srv.do_list(status="active")
    assert [e["id"] for e in parent] == [old["id"]]
