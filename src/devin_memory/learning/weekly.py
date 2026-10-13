"""Public weekly learning report — aggregate counts only, safe to share.

Unlike ``REPORT.md`` (which carries lesson text and per-node provenance for
reviewers), the weekly report is the *public* surface of the learning loop:
it contains no session text, no session/node identifiers and no filesystem
paths — only dates, theme names from the fixed topic table, and counts.
The output is meant to be committed or pasted into public docs.

Cursor leg of the incrementality spec (devin-powerups/docs/incrementality.md):
the CLI drives the ``devin-learning-weekly`` cursor; this module only builds,
renders and atomically writes the artifact.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .review import Verdict
from .skills import topic_for


def _iso_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def week_label(ms: int) -> str:
    """ISO ``YYYY-Www`` label for the report window end."""
    iso = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _reason_bucket(reason: str) -> str:
    """Collapse a review reason to a public-safe taxonomy label.

    ``secret:<category>:<pattern>`` → ``secret:<category>`` (pattern names
    stay internal); ``injection:<name>`` labels are already fixed enum
    values and pass through.
    """
    if reason.startswith("secret:"):
        return ":".join(reason.split(":")[:2])
    return reason


def build_weekly(
    verdicts: list[Verdict], *, since_ms: int, until_ms: int
) -> dict[str, Any]:
    """Aggregate verdicts into the public weekly report payload.

    Counts only: theme histogram over accepted lessons, promoted skill
    names with lesson counts, quarantine-pending reason buckets, and the
    number of distinct sessions lessons came from. No text survives.
    """
    accepted = [v for v in verdicts if v.accepted]
    dropped = [v for v in verdicts if not v.accepted]
    themes: dict[str, int] = {}
    for v in accepted:
        topic = topic_for(v.candidate.text)
        themes[topic] = themes.get(topic, 0) + 1
    quarantine: dict[str, int] = {}
    for v in dropped:
        for reason in v.reasons:
            bucket = _reason_bucket(reason)
            quarantine[bucket] = quarantine.get(bucket, 0) + 1
    return {
        "tool": "devin-learning",
        "version": __version__,
        "kind": "weekly-public-report",
        "week": week_label(until_ms),
        "since_ms": since_ms,
        "until_ms": until_ms,
        "window": f"{_iso_date(since_ms) if since_ms > 0 else 'all history'}"
        f" → {_iso_date(until_ms)} (UTC)",
        "sessions": len({v.candidate.session_id for v in verdicts}),
        "candidates": len(verdicts),
        "accepted": len(accepted),
        "dropped": len(dropped),
        "themes": dict(sorted(themes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "skills": [
            {"skill": f"learned-{topic}", "lessons": count}
            for topic, count in sorted(themes.items())
        ],
        "quarantine": dict(sorted(quarantine.items())),
    }


def render_weekly_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Weekly learning report — {report['week']}",
        "",
        "> Public-safe aggregate from `devin-learning weekly-report`:",
        "> counts, themes and dates only — no session text, paths or",
        "> identifiers, so this file is safe to commit and share.",
        "",
        f"- window: {report['window']}",
        f"- sessions with lessons: {report['sessions']}",
        (
            f"- lesson candidates: {report['candidates']}"
            f" (accepted {report['accepted']}, quarantined {report['dropped']})"
        ),
        "",
        "## Lessons by theme",
        "",
    ]
    if report["themes"]:
        lines += [f"- {topic}: {n}" for topic, n in report["themes"].items()]
    else:
        lines.append("_None this window._")
    lines += ["", "## New skills promoted", ""]
    if report["skills"]:
        lines += [
            f"- {item['skill']} ({item['lessons']} lesson(s))"
            for item in report["skills"]
        ]
    else:
        lines.append("_None this window._")
    lines += ["", "## Quarantined items pending review", ""]
    if report["quarantine"]:
        lines += [f"- {bucket}: {n}" for bucket, n in report["quarantine"].items()]
    else:
        lines.append("_None this window._")
    lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    """tmp + ``os.replace`` — never a partial report (envelope rule 1)."""
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_weekly_report(report: dict[str, Any], out_dir: str | Path) -> Path:
    """Write ``weekly-<YYYY>-W<ww>.md`` inside ``out_dir``; returns the path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"weekly-{report['week']}.md"
    _atomic_write(target, render_weekly_markdown(report))
    return target
