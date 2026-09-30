"""Report contract: JSON shape and markdown summary."""

import json

from devin_memory.learning.extract import extract_candidates
from devin_memory.learning.report import build_report, render_markdown
from devin_memory.learning.review import review_candidates

from conftest import FAKE_API_KEY


def _verdicts(sessions_db):
    return review_candidates(extract_candidates(sessions_db))


def test_report_json_shape(sessions_db):
    report = build_report(sessions_db, _verdicts(sessions_db), written=[])
    assert report["tool"] == "devin-learning"
    assert report["version"]
    assert report["candidates"] == 8
    assert report["accepted"] == 4
    assert report["dropped"] == 4
    for item in report["accepted_items"]:
        assert {"text", "topic", "session_id", "node_id", "created_at"} <= set(item)
    for item in report["dropped_items"]:
        assert {"preview", "reasons", "session_id", "node_id"} <= set(item)
        assert item["reasons"]


def test_dropped_lesson_text_is_never_echoed(sessions_db):
    report = build_report(sessions_db, _verdicts(sessions_db), written=[])
    blob = json.dumps(report)
    assert FAKE_API_KEY not in blob
    md = render_markdown(report)
    assert FAKE_API_KEY not in md


def test_markdown_summary_lists_both_sides(sessions_db):
    md = render_markdown(
        build_report(sessions_db, _verdicts(sessions_db), written=[])
    )
    assert md.startswith("# devin-learning report")
    assert "accepted: 4" in md and "dropped: 4" in md
    assert "## Accepted" in md and "## Dropped" in md
    assert "Always run pytest before pushing." in md
    # Dropped entries carry their reasons.
    assert "secret:api_key" in md


def test_report_deterministic(sessions_db):
    a = build_report(sessions_db, _verdicts(sessions_db), written=[])
    b = build_report(sessions_db, _verdicts(sessions_db), written=[])
    assert a == b
