"""Safety gate: secrets and injection shapes are dropped with reasons."""

from devin_memory.learning.extract import extract_candidates
from devin_memory.learning.review import review_candidates

from conftest import FAKE_API_KEY, FAKE_B64_BLOB


def _verdicts(sessions_db):
    return review_candidates(extract_candidates(sessions_db))


def _verdict_for(verdicts, needle):
    return next(v for v in verdicts if needle in v.candidate.text)


def test_secret_bearing_lesson_is_dropped(sessions_db):
    v = _verdict_for(_verdicts(sessions_db), FAKE_API_KEY)
    assert not v.accepted
    assert any(r.startswith("secret:api_key") for r in v.reasons)


def test_ignore_previous_instructions_is_dropped(sessions_db):
    v = _verdict_for(_verdicts(sessions_db), "Ignore all previous instructions")
    assert not v.accepted
    assert any(r.startswith("injection:") for r in v.reasons)


def test_base64_blob_is_dropped(sessions_db):
    v = _verdict_for(_verdicts(sessions_db), FAKE_B64_BLOB)
    assert not v.accepted
    assert any(r == "injection:base64_blob" for r in v.reasons)


def test_tool_call_json_blob_is_dropped(sessions_db):
    v = _verdict_for(_verdicts(sessions_db), '"tool_call_id"')
    assert not v.accepted
    assert any(r == "injection:tool_call_blob" for r in v.reasons)


def test_genuine_lessons_are_accepted(sessions_db):
    verdicts = _verdicts(sessions_db)
    accepted_texts = {v.candidate.text for v in verdicts if v.accepted}
    assert "Always run pytest before pushing." in accepted_texts
    assert "Prefira rebase em vez de merge." in accepted_texts
    assert "Don't commit secrets to the repository." in accepted_texts
    assert "Remember to update the changelog afterwards." in accepted_texts


def test_every_candidate_gets_a_verdict(sessions_db):
    candidates = extract_candidates(sessions_db)
    verdicts = review_candidates(candidates)
    assert len(verdicts) == len(candidates)
    assert all(v.accepted == (not v.reasons) for v in verdicts)


def test_verdicts_are_deterministic(sessions_db):
    first = [(v.candidate.text, v.accepted, v.reasons) for v in _verdicts(sessions_db)]
    second = [(v.candidate.text, v.accepted, v.reasons) for v in _verdicts(sessions_db)]
    assert first == second
