"""``compact`` (dedup + vacuum) and ``quarantine --digest`` (audit hash).

Pin the semantics: dedup groups on exact (content, workspace, profile)
among non-retracted rows, keeps the liveliest-then-oldest copy, retracts
the rest — never deletes. The digest keys on content fingerprints (not
row ids) so it is stable across runs and machines and moves on any
membership/reason change. Reports carry no content.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from fixtures import CLEAN_FACT, CLEAN_FACT_2, SECRET_FACT

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# compact — plan semantics
# ---------------------------------------------------------------------------


def test_compact_survivor_prefers_unexpired_copy(store):
    """An expired duplicate must not win survivor selection — keeping
    it would retract the only live copy recall can serve."""
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    old = ops.retain(store, CLEAN_FACT, expires_at=past)
    live = ops.retain(store, CLEAN_FACT, expires_at=future)

    report = ops.compact(store, apply=True)

    (group,) = report["groups"]
    assert group["keep_id"] == live.id
    assert store.get(old.id).status == "retracted"
    assert store.get(live.id).status == "active"
    # the merged copy keeps the furthest expiry — the intended lifetime
    assert store.get(live.id).expires_at == future


def test_compact_survivor_prefers_no_expiry_over_expired(store):
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old = ops.retain(store, CLEAN_FACT, expires_at=past)
    live = ops.retain(store, CLEAN_FACT)

    ops.compact(store, apply=True)

    assert store.get(live.id).status == "active"
    assert store.get(old.id).status == "retracted"


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


def test_compact_never_merges_tags_across_status(store):
    """Unreviewed tags must not reach an active entry through dedup — a
    quarantined/proposed copy's tags never bleed into the survivor."""
    flagged = ops.retain(store, SECRET_FACT, tags=["poison-tag"])
    released = ops.retain(store, SECRET_FACT, tags=["kept"])
    ops.release(store, released.id)
    assert flagged.status == "quarantined"
    ops.compact(store, apply=True)
    survivor = store.get(released.id)
    assert survivor.status == "active"
    assert "poison-tag" not in survivor.tags
    assert "kept" in survivor.tags


def test_compact_retracted_rows_do_not_group(store):
    old = ops.retain(store, CLEAN_FACT)
    ops.retract(store, old.id)
    new = ops.retain(store, CLEAN_FACT)  # re-retained: history, not a dup
    report = ops.compact(store)
    assert report["duplicate_groups"] == 0
    assert store.get(old.id).status == "retracted"
    assert store.get(new.id).status == "active"


def test_compact_keeps_one_copy_per_profile(store):
    """prime() filters by profile — merging across profiles would retract
    the only copy the other profile's context still sees."""
    corp = ops.retain(store, CLEAN_FACT, profile="corporate")
    pers = ops.retain(store, CLEAN_FACT, profile="personal")
    report = ops.compact(store, apply=True)
    assert report["duplicate_groups"] == 0
    assert store.get(corp.id).status == "active"
    assert store.get(pers.id).status == "active"
    assert CLEAN_FACT in ops.prime(store, profile="corporate")
    assert CLEAN_FACT in ops.prime(store, profile="personal")


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
        assert report["vacuumed"] is True
        assert report["vacuum_error"] is None
        assert report["db_bytes_after"] is not None
        assert report["db_bytes_after"] <= report["db_bytes_before"]
        assert report["db_bytes_after"] == db.stat().st_size


def test_compact_apply_replans_when_survivor_retracted(store):
    """A retraction committed between plan and apply must not make dedup
    remove the last live copy — apply re-plans under the write lock."""
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT)
    plan = ops.compact(store)
    assert plan["groups"][0]["keep_id"] == a.id
    ops.retract(store, a.id)  # planned survivor disappears mid-flight
    report = ops.compact(store, apply=True)
    assert report["groups"][0]["keep_id"] == b.id
    statuses = {e.id: e.status for e in store.entries()}
    assert statuses[a.id] == "retracted"
    assert statuses[b.id] == "active"  # fact still recallable
    live = [e for e in store.entries() if e.status != "retracted"]
    assert [e.id for e in live] == [b.id]


def test_compact_apply_never_retracts_last_live_copy(store):
    ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT)
    plan = ops.compact(store)
    ops.retract(store, plan["groups"][0]["keep_id"])
    report = ops.compact(store, apply=True)
    assert report["duplicate_entries"] == 0  # nothing left to merge
    assert store.get(b.id).status == "active"


def test_compact_apply_rolls_back_all_groups_on_failure(store, monkeypatch):
    """Dedup is one transaction: a mid-apply failure commits nothing."""
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT_2)
    ops.retain(store, CLEAN_FACT_2)
    real_set_status = store.set_status
    calls = 0

    def flaky(entry_id, status):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("simulated write failure")
        real_set_status(entry_id, status)

    monkeypatch.setattr(store, "set_status", flaky)
    with pytest.raises(sqlite3.OperationalError):
        ops.compact(store, apply=True)
    assert all(e.status == "active" for e in store.entries())


def test_compact_apply_reports_vacuum_failure(store, monkeypatch):
    """Vacuum runs after the dedup commit; its failure is reported
    without masking the dedup that did happen."""
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT)

    def fail_vacuum():
        raise sqlite3.OperationalError("no space for vacuum image")

    monkeypatch.setattr(store, "vacuum", fail_vacuum)
    report = ops.compact(store, apply=True)
    assert report["vacuumed"] is False
    assert "no space" in report["vacuum_error"]
    assert report["duplicate_entries"] == 1  # dedup itself committed
    assert store.get(a.id).status == "active"
    assert store.get(b.id).status == "retracted"


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


def test_quarantine_digest_distinguishes_newline_reason_lists(store):
    """["manual:a\\nmanual:b"] and ["manual:a", "manual:b"] hash the same
    under a "\\n".join — the fingerprint must keep them apart."""
    e = store.insert(
        "a dubious but shapeless fact",
        status="quarantined",
        quarantine_reasons=["manual:a\nmanual:b"],
    )
    before = ops.quarantine_digest(store)["digest"]
    store.set_quarantine_reasons(e.id, ["manual:a", "manual:b"])
    assert ops.quarantine_digest(store)["digest"] != before


def test_quarantine_digest_never_echoes_spoofed_family_prefix(store):
    """--reason accepts arbitrary text; a manual reason wearing a
    taxonomy prefix must still bucket without echoing its payload."""
    e = ops.retain(store, CLEAN_FACT)
    ops.quarantine_entry(store, e.id, reason="secret:hunter2")
    digest = ops.quarantine_digest(store)
    assert "hunter2" not in json.dumps(digest)
    assert digest["reason_counts"] == {"secret:other": 1}


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


def test_compact_cli_vacuum_failure_still_reports_dedup(
    db, capsys, monkeypatch
):
    main(["--db", db, "retain", CLEAN_FACT])
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()

    def fail_vacuum(self):
        raise sqlite3.OperationalError("ioerr")

    monkeypatch.setattr(MemoryStore, "vacuum", fail_vacuum)
    rc = main(["--db", db, "compact", "--apply", "--json"])
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert rc == 1
    assert "vacuum failed" in out.err
    assert report["duplicate_entries"] == 1  # dedup committed anyway
    assert report["vacuumed"] is False
    assert report["vacuum_error"]


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
