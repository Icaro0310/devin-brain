"""``compact`` (dedup + vacuum) and ``quarantine --digest`` (audit hash).

Pin the semantics: dedup groups on exact (content, workspace) among
non-retracted rows, keeps the liveliest-then-oldest copy, retracts the
rest — never deletes. The digest keys on content fingerprints (not row
ids) so it is stable across runs and machines and moves on any
membership/reason change. Reports carry no content.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, CLEAN_FACT_2, SECRET_FACT

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# compact — plan semantics
# ---------------------------------------------------------------------------


def test_compact_finds_exact_content_duplicates(store):
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT)  # retain does not dedupe
    ops.retain(store, CLEAN_FACT_2)
    report = ops.compact(store)
    assert report["dry_run"] is True
    assert report["duplicate_groups"] == 1
    assert report["duplicate_entries"] == 1
    group = report["groups"][0]
    assert group["keep_id"] == a.id  # oldest copy survives
    assert group["drop_ids"] == [b.id]
    assert report["entries_live"] == 3
    assert report["entries_live_after"] == 2


def test_compact_is_deterministic(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT)
    first = ops.compact(store)
    second = ops.compact(store)
    assert first == second


def test_compact_never_echoes_content(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT)
    report = ops.compact(store)
    assert CLEAN_FACT not in json.dumps(report)
    assert report["groups"][0]["content_sha256"] == hashlib.sha256(
        CLEAN_FACT.encode()
    ).hexdigest()[:12]


def test_compact_ignores_distinct_content_and_scope(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT_2)  # different content
    ops.retain(store, CLEAN_FACT, workspace="/elsewhere")  # other scope
    report = ops.compact(store)
    assert report["duplicate_groups"] == 0
    assert report["duplicate_entries"] == 0


def test_compact_prefers_active_survivor_over_quarantined(store):
    quarantined = ops.retain(store, SECRET_FACT)
    released = ops.retain(store, SECRET_FACT)
    ops.release(store, released.id)  # same content, now active
    report = ops.compact(store, apply=True)
    group = report["groups"][0]
    assert group["keep_id"] == released.id  # liveliest status wins over age
    assert group["drop_ids"] == [quarantined.id]
    assert store.get(released.id).status == "active"
    assert store.get(quarantined.id).status == "retracted"


def test_compact_retracted_rows_do_not_group(store):
    old = ops.retain(store, CLEAN_FACT)
    ops.retract(store, old.id)
    new = ops.retain(store, CLEAN_FACT)  # re-retained: history, not a dup
    report = ops.compact(store)
    assert report["duplicate_groups"] == 0
    assert store.get(old.id).status == "retracted"
    assert store.get(new.id).status == "active"


# ---------------------------------------------------------------------------
# compact — dry-run vs apply
# ---------------------------------------------------------------------------


def test_compact_dry_run_writes_nothing(store, tmp_path):
    db = tmp_path / "memory.db"
    with MemoryStore(db) as s:
        ops.retain(s, CLEAN_FACT)
        ops.retain(s, CLEAN_FACT)
        before = [e.to_dict() for e in s.entries()]
        bytes_before = db.stat().st_size
        report = ops.compact(s)  # dry-run
        assert report["duplicate_entries"] == 1
        assert [e.to_dict() for e in s.entries()] == before
        assert db.stat().st_size == bytes_before


def test_compact_apply_retracts_copies_and_never_deletes(store):
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT)
    total_before = len(store.entries())
    report = ops.compact(store, apply=True)
    assert report["dry_run"] is False
    assert report["duplicate_entries"] == 2
    # rows are retracted, not deleted — total row count is unchanged
    assert len(store.entries()) == total_before
    statuses = {e.id: e.status for e in store.entries()}
    assert statuses[a.id] == "active"
    assert statuses[b.id] == "retracted"
    assert len(ops.recall(store, "sessions")) == 1
    # re-running is idempotent — nothing left to merge
    assert ops.compact(store)["duplicate_entries"] == 0


def test_compact_apply_merges_tags_and_reasons(store):
    a = ops.retain(store, CLEAN_FACT, tags=["one"])
    ops.retain(store, CLEAN_FACT, tags=["two", "three"])
    ops.compact(store, apply=True)
    assert set(store.get(a.id).tags) == {"one", "two", "three"}


def test_compact_apply_vacuums_file(tmp_path):
    db = tmp_path / "memory.db"
    with MemoryStore(db) as s:
        for _ in range(3):
            ops.retain(s, CLEAN_FACT)
        report = ops.compact(s, apply=True)
        assert report["db_bytes_after"] is not None
        assert report["db_bytes_after"] <= report["db_bytes_before"]
        assert report["db_bytes_after"] == db.stat().st_size


# ---------------------------------------------------------------------------
# quarantine digest
# ---------------------------------------------------------------------------


def test_quarantine_digest_empty_lane(store):
    digest = ops.quarantine_digest(store)
    assert digest["count"] == 0
    assert digest["reason_counts"] == {}
    assert digest["digest"] == EMPTY_SHA256
    assert digest["algorithm"] == "sha256"


def test_quarantine_digest_stable_across_runs(store):
    ops.retain(store, SECRET_FACT)
    ops.retain(store, CLEAN_FACT)
    first = ops.quarantine_digest(store)
    second = ops.quarantine_digest(store)
    assert first == second
    assert first["count"] == 1


def test_quarantine_digest_moves_on_membership_change(store):
    e = ops.retain(store, SECRET_FACT)
    before = ops.quarantine_digest(store)["digest"]
    ops.retain(store, "sk-" + "B" * 24)  # second secret lands too
    assert ops.quarantine_digest(store)["digest"] != before
    mid = ops.quarantine_digest(store)["digest"]
    ops.release(store, e.id)  # leaves the lane -> digest moves again
    after = ops.quarantine_digest(store)
    assert after["digest"] != mid
    assert after["count"] == 1


def test_quarantine_digest_moves_on_reason_change(store):
    e = ops.retain(store, "a dubious but shapeless fact")
    ops.quarantine_entry(store, e.id, reason="manual:audit")
    before = ops.quarantine_digest(store)["digest"]
    ops.quarantine_entry(store, e.id, reason="manual:recheck")
    assert ops.quarantine_digest(store)["digest"] != before


def test_quarantine_digest_keys_on_content_not_ids(store, tmp_path):
    """Same quarantined content in a different store (different row ids)
    produces the same digest — the cross-machine audit property."""
    ops.retain(store, SECRET_FACT)
    digest_a = ops.quarantine_digest(store)["digest"]
    other_path = tmp_path / "other.db"
    with MemoryStore(other_path) as other:
        ops.retain(other, CLEAN_FACT)  # different insertion order / ids
        ops.retain(other, SECRET_FACT)
        digest_b = ops.quarantine_digest(other)["digest"]
    assert digest_a == digest_b


def test_quarantine_digest_reports_families_not_content(store):
    ops.retain(store, SECRET_FACT)
    ops.quarantine_entry(store, ops.retain(store, CLEAN_FACT).id,
                         reason="manual:pasted hunter2 password")
    digest = ops.quarantine_digest(store)
    blob = json.dumps(digest)
    assert SECRET_FACT not in blob
    assert "hunter2" not in blob  # free-form manual reason never echoed
    assert digest["reason_counts"]["manual:*"] == 1
    assert any(k.startswith("secret:") for k in digest["reason_counts"])


def test_quarantine_digest_is_read_only(store):
    ops.retain(store, SECRET_FACT)
    before = [e.to_dict() for e in store.entries()]
    ops.quarantine_digest(store)
    assert [e.to_dict() for e in store.entries()] == before


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "memory.db")


def test_compact_cli_dry_run_then_apply(db, capsys):
    main(["--db", db, "retain", CLEAN_FACT])
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()

    assert main(["--db", db, "compact"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "2 live entries -> 1" in out

    rows = main(["--db", db, "list", "--json"])
    assert rows == 0
    listed = json.loads(capsys.readouterr().out)
    assert all(r["status"] == "active" for r in listed)  # nothing changed

    assert main(["--db", db, "compact", "--apply", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is False
    assert report["duplicate_entries"] == 1

    main(["--db", db, "list", "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert {r["status"] for r in listed} == {"active", "retracted"}


def test_quarantine_digest_cli_json(db, capsys):
    main(["--db", db, "retain", SECRET_FACT])
    capsys.readouterr()
    assert main(["--db", db, "quarantine", "--digest", "--json"]) == 0
    digest = json.loads(capsys.readouterr().out)
    assert digest["count"] == 1
    assert len(digest["digest"]) == 64
    # and the lane itself is untouched (read path)
    main(["--db", db, "quarantine", "--json"])
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_quarantine_digest_cli_rejects_mutation_flags(db, capsys):
    main(["--db", db, "retain", SECRET_FACT])
    capsys.readouterr()
    rc = main(["--db", db, "quarantine", "1", "--digest"])
    assert rc == 1
    assert "read-only" in capsys.readouterr().err
    rc = main(["--db", db, "quarantine", "--digest", "--release", "1"])
    assert rc == 1


def test_compact_fails_closed_on_corrupt_db(tmp_path, capsys):
    corrupt = tmp_path / "memory.db"
    corrupt.write_bytes(b"this is not a sqlite database at all")
    assert main(["--db", str(corrupt), "compact"]) == 1
    assert "error:" in capsys.readouterr().err
    # file untouched — no recovery attempted on a read path's sibling
    assert corrupt.read_bytes() == b"this is not a sqlite database at all"


def test_quarantine_digest_fails_closed_on_corrupt_db(tmp_path, capsys):
    corrupt = tmp_path / "memory.db"
    corrupt.write_bytes(b"not sqlite")
    assert main(["--db", str(corrupt), "quarantine", "--digest"]) == 1
    assert "error:" in capsys.readouterr().err
