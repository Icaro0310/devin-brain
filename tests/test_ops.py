"""Ops tests: retain/recall/retract/supersede/release + provenance checks."""

from __future__ import annotations

import pytest

from devin_memory import ops
from devin_memory.store import MemoryStore

from fixtures import (
    CLEAN_FACT,
    CLEAN_FACT_2,
    INJECTION_FACT,
    SECRET_FACT,
    make_sessions_db,
)


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# retain
# ---------------------------------------------------------------------------


def test_retain_clean_fact_is_active(store):
    e = ops.retain(store, CLEAN_FACT, tags=["internals", "internals", " sqlite "])
    assert e.status == "active"
    assert e.tags == ("internals", "sqlite")  # deduped + stripped
    assert e.quarantine_reasons == ()


def test_retain_secret_goes_to_quarantine(store):
    e = ops.retain(store, SECRET_FACT)
    assert e.status == "quarantined"
    assert any(r.startswith("secret:") for r in e.quarantine_reasons)


def test_retain_injection_goes_to_quarantine(store):
    e = ops.retain(store, INJECTION_FACT)
    assert e.status == "quarantined"
    assert any(r.startswith("injection:") for r in e.quarantine_reasons)


def test_retain_rejects_empty_content(store):
    with pytest.raises(ValueError):
        ops.retain(store, "   ")


def test_retain_records_provenance(store):
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-9", source_rowid=7)
    assert e.source_session_id == "sess-9"
    assert e.source_rowid == 7


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


def test_recall_returns_only_active(store):
    ops.retain(store, "sqlite stores the facts")
    ops.retain(store, SECRET_FACT + " sqlite")  # quarantined, still matches kw
    hits = ops.recall(store, "sqlite")
    assert len(hits) == 1
    assert hits[0].status == "active"


def test_recall_ranks_relevant_first(store):
    weak = ops.retain(store, "mentions sqlite once")
    tagged = ops.retain(store, "database notes", tags=["sqlite"])
    frequent = ops.retain(store, "sqlite sqlite sqlite internals")
    hits = ops.recall(store, "sqlite")
    assert [e.id for e in hits] == [frequent.id, tagged.id, weak.id]


def test_recall_empty_query_returns_most_recent(store):
    a = ops.retain(store, CLEAN_FACT)
    b = ops.retain(store, CLEAN_FACT_2)
    hits = ops.recall(store, "")
    assert [e.id for e in hits] == [b.id, a.id]


def test_recall_limit_and_tag_filter(store):
    ops.retain(store, "alpha one", tags=["a"])
    ops.retain(store, "alpha two", tags=["b"])
    ops.retain(store, "alpha three", tags=["a", "b"])
    hits = ops.recall(store, "alpha", tags=["b"])
    assert {e.content for e in hits} == {"alpha two", "alpha three"}
    assert len(ops.recall(store, "alpha", limit=2)) == 2


def test_recall_no_match_returns_empty(store):
    ops.retain(store, CLEAN_FACT)
    assert ops.recall(store, "nonexistentterm") == []


# ---------------------------------------------------------------------------
# retract / release
# ---------------------------------------------------------------------------


def test_retract_marks_entry_retracted(store):
    e = ops.retain(store, CLEAN_FACT)
    out = ops.retract(store, e.id)
    assert out.status == "retracted"
    assert ops.recall(store, "stores") == []


def test_release_returns_quarantined_to_active(store):
    e = ops.retain(store, SECRET_FACT)
    assert e.status == "quarantined"
    out = ops.release(store, e.id)
    assert out.status == "active"
    # reasons are kept for audit even after release
    assert out.quarantine_reasons


def test_release_rejects_non_quarantined(store):
    e = ops.retain(store, CLEAN_FACT)
    with pytest.raises(ops.InvalidTransitionError):
        ops.release(store, e.id)


def test_retract_is_not_idempotent(store):
    e = ops.retain(store, CLEAN_FACT)
    ops.retract(store, e.id)
    with pytest.raises(ops.InvalidTransitionError):
        ops.retract(store, e.id)


def test_missing_entry_raises(store):
    with pytest.raises(ops.EntryNotFoundError):
        ops.retract(store, 4242)


# ---------------------------------------------------------------------------
# supersede
# ---------------------------------------------------------------------------


def test_supersede_keeps_history(store):
    old = ops.retain(store, "schema is v15", tags=["internals"])
    new = ops.supersede(store, old.id, "schema is v17", tags=["internals"])

    assert new.version == 2
    assert new.supersedes_id == old.id
    assert new.status == "active"
    # history: old row still exists, marked retracted
    gone = store.get(old.id)
    assert gone.status == "retracted"
    assert gone.version == 1
    # recall sees only the new version
    assert [e.id for e in ops.recall(store, "schema")] == [new.id]


def test_supersede_quarantined_new_still_retires_old(store):
    old = ops.retain(store, CLEAN_FACT)
    new = ops.supersede(store, old.id, SECRET_FACT)
    assert new.status == "quarantined"
    assert new.version == 2
    assert store.get(old.id).status == "retracted"


def test_supersede_requires_active_source(store):
    old = ops.retain(store, CLEAN_FACT)
    ops.retract(store, old.id)
    with pytest.raises(ops.InvalidTransitionError):
        ops.supersede(store, old.id, "replacement")


# ---------------------------------------------------------------------------
# list_entries
# ---------------------------------------------------------------------------


def test_list_entries_filters_by_status(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, SECRET_FACT)
    assert len(ops.list_entries(store)) == 2
    assert len(ops.list_entries(store, status="quarantined")) == 1
    assert len(ops.list_entries(store, status="active")) == 1


# ---------------------------------------------------------------------------
# provenance (via devin-internals-spec fixtures)
# ---------------------------------------------------------------------------


def test_verify_provenance_against_sessions_db(store, tmp_path):
    sessions_db, session_id, rowid = make_sessions_db(tmp_path)
    e = ops.retain(
        store, CLEAN_FACT, source_session_id=session_id, source_rowid=rowid
    )
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["checked"] is True
    assert report["session_found"] is True
    assert report["rowid_found"] is True


def test_verify_provenance_flags_unknown_session(store, tmp_path):
    sessions_db, _, _ = make_sessions_db(tmp_path)
    e = ops.retain(store, CLEAN_FACT, source_session_id="sess-not-real")
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["checked"] is True
    assert report["session_found"] is False


def test_verify_provenance_flags_wrong_rowid(store, tmp_path):
    sessions_db, session_id, _ = make_sessions_db(tmp_path)
    e = ops.retain(
        store, CLEAN_FACT, source_session_id=session_id, source_rowid=99999
    )
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["session_found"] is True
    assert report["rowid_found"] is False


def test_verify_provenance_no_source(store, tmp_path):
    sessions_db, _, _ = make_sessions_db(tmp_path)
    e = ops.retain(store, CLEAN_FACT)
    report = ops.verify_provenance(store, e.id, sessions_db)
    assert report["checked"] is False
