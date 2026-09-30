"""Topic grouping, SKILL.md draft format, and the live-skills write guard."""

import pytest

from devin_memory.learning.extract import extract_candidates
from devin_memory.learning.review import review_candidates
from devin_memory.learning.skills import (
    LiveSkillsDirError,
    emit_drafts,
    group_by_topic,
    render_skill,
    topic_for,
)

from conftest import FAKE_API_KEY, FAKE_B64_BLOB, LESSON_SESSION_ID


def _accepted(sessions_db):
    return [v for v in review_candidates(extract_candidates(sessions_db)) if v.accepted]


def test_topic_for_keyword_buckets():
    assert topic_for("Always run pytest before pushing.") == "testing"
    assert topic_for("Prefira rebase em vez de merge.") == "git-workflow"
    assert topic_for("Don't commit secrets to the repository.") == "security"
    assert topic_for("Remember to update the changelog afterwards.") == "docs"


def test_topic_for_falls_back_to_geral():
    assert topic_for("Always hydrate the gerbils.") == "geral"


def test_group_by_topic_clusters_accepted(sessions_db):
    groups = group_by_topic(_accepted(sessions_db))
    assert set(groups) == {"testing", "git-workflow", "security", "docs"}
    assert all(len(v) == 1 for v in groups.values())


def test_render_skill_frontmatter_and_bullets(sessions_db):
    groups = group_by_topic(_accepted(sessions_db))
    content = render_skill("testing", groups["testing"])
    assert content.startswith("---\nname: learned-testing\n")
    assert 'description: "' in content
    assert "# Learned lessons: testing" in content
    assert "- (2026-09-29) Always run pytest before pushing." in content
    assert "## Lessons" in content
    assert "## Changelog" in content


def test_emit_drafts_writes_learned_dirs(sessions_db, tmp_path):
    out = tmp_path / "drafts"
    written = emit_drafts(_accepted(sessions_db), out)
    assert (out / "learned-testing" / "SKILL.md").is_file()
    assert (out / "learned-git-workflow" / "SKILL.md").is_file()
    assert len(written) == 4
    # Every emitted path lives inside --out.
    assert all(str(p).startswith(str(out.resolve())) for p in written)


def test_dropped_lessons_never_reach_disk(sessions_db, tmp_path):
    out = tmp_path / "drafts"
    emit_drafts(review_candidates(extract_candidates(sessions_db)), out)
    corpus = "\n".join(
        p.read_text(encoding="utf-8") for p in out.rglob("SKILL.md")
    )
    assert FAKE_API_KEY not in corpus
    assert FAKE_B64_BLOB not in corpus
    assert "Ignore all previous instructions" not in corpus
    assert '"tool_call_id"' not in corpus


def test_live_skills_dir_refused_without_apply(sessions_db, tmp_path):
    live = tmp_path / ".devin" / "skills"
    with pytest.raises(LiveSkillsDirError):
        emit_drafts(_accepted(sessions_db), live)
    assert not live.exists()


def test_live_skills_dir_writes_with_apply(sessions_db, tmp_path):
    live = tmp_path / ".devin" / "skills"
    written = emit_drafts(_accepted(sessions_db), live, apply=True)
    assert (live / "learned-testing" / "SKILL.md").is_file()
    assert len(written) == 4
