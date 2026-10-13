"""Extraction recall: lessons found, agent messages and noise ignored."""

from devin_memory.learning.extract import extract_candidates

from conftest import EXPECTED_LESSON_TEXTS, LESSON_SESSION_ID


def test_extracts_all_planted_lessons(sessions_db):
    candidates = extract_candidates(sessions_db)
    texts = [c.text for c in candidates]
    for expected in EXPECTED_LESSON_TEXTS:
        assert expected in texts, f"missing lesson: {expected!r}"


def test_ignores_agent_messages(sessions_db):
    candidates = extract_candidates(sessions_db)
    assert not any("I already do this" in c.text for c in candidates)


def test_ignores_non_lesson_user_messages(sessions_db):
    candidates = extract_candidates(sessions_db)
    assert not any("flaky test" in c.text for c in candidates)
    # Fixture-generated rows ("fixture message i.n") are not lessons either.
    assert not any("fixture message" in c.text for c in candidates)


def test_splits_sentences_within_a_message(sessions_db):
    candidates = extract_candidates(sessions_db)
    assert not any("Please fix the parser" in c.text for c in candidates)
    assert any(
        c.text == "Remember to update the changelog afterwards."
        for c in candidates
    )


def test_candidates_carry_provenance(sessions_db):
    candidates = extract_candidates(sessions_db)
    lesson = next(c for c in candidates if c.text.startswith("Always run pytest"))
    assert lesson.session_id == LESSON_SESSION_ID
    assert lesson.node_id == 1
    assert lesson.created_at > 0
    assert lesson.source == "message_nodes"


def test_candidates_ordered_deterministically(sessions_db):
    first = [(c.session_id, c.node_id, c.text) for c in extract_candidates(sessions_db)]
    second = [(c.session_id, c.node_id, c.text) for c in extract_candidates(sessions_db)]
    assert first == second


def test_since_filters_old_nodes(sessions_db):
    all_c = extract_candidates(sessions_db)
    assert all_c
    times = sorted({c.created_at for c in all_c})
    hi_water = times[-1]
    # watermark above everything → nothing
    assert extract_candidates(sessions_db, since=hi_water + 1) == []
    # watermark at the max → every candidate is at-or-below → all excluded
    assert extract_candidates(sessions_db, since=hi_water) == []
    # watermark just below the newest → only strictly-newer candidates pass
    below = extract_candidates(sessions_db, since=hi_water - 1)
    assert below == [c for c in all_c if c.created_at == hi_water]
    assert 0 < len(below) < len(all_c)


def test_scan_watermark_covers_non_candidates(sessions_db):
    from devin_memory.learning.extract import scan_watermark

    wm = scan_watermark(sessions_db)
    assert wm >= max(c.created_at for c in extract_candidates(sessions_db))
