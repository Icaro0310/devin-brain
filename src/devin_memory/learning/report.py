"""Markdown + JSON summary of an extract run.

Dropped lessons are *never* echoed verbatim: their preview is passed through
``devin_redact.engine.redact_text`` (secrets become ``<REDACTED:fp>``) and
truncated, so the report itself is safe to share.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devin_redact.engine import redact_text

from . import __version__
from .review import Verdict
from .skills import topic_for

_PREVIEW_LIMIT = 120


def _safe_preview(text: str) -> str:
    redacted, _ = redact_text(text)
    if len(redacted) > _PREVIEW_LIMIT:
        redacted = redacted[: _PREVIEW_LIMIT - 1] + "…"
    return redacted


def build_report(
    db_path: str | Path, verdicts: list[Verdict], *, written: list[Path]
) -> dict[str, Any]:
    accepted = [v for v in verdicts if v.accepted]
    dropped = [v for v in verdicts if not v.accepted]
    return {
        "tool": "devin-learning",
        "version": __version__,
        "sessions_db": str(db_path),
        "candidates": len(verdicts),
        "accepted": len(accepted),
        "dropped": len(dropped),
        "accepted_items": [
            {
                "text": v.candidate.text,
                "topic": topic_for(v.candidate.text),
                "session_id": v.candidate.session_id,
                "node_id": v.candidate.node_id,
                "created_at": v.candidate.created_at,
                "warnings": list(v.warnings),
            }
            for v in accepted
        ],
        "dropped_items": [
            {
                "preview": _safe_preview(v.candidate.text),
                "reasons": list(v.reasons),
                "session_id": v.candidate.session_id,
                "node_id": v.candidate.node_id,
            }
            for v in dropped
        ],
        "written": [str(p) for p in written],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# devin-learning report",
        "",
        f"- source: `{report['sessions_db']}`",
        f"- candidates: {report['candidates']} — "
        f"accepted: {report['accepted']}, dropped: {report['dropped']}",
        "",
        "## Accepted",
        "",
    ]
    for item in report["accepted_items"]:
        warnings = f" ⚠ {', '.join(item['warnings'])}" if item["warnings"] else ""
        lines.append(
            f"- **[learned-{item['topic']}]** {item['text']} "
            f"_(session `{item['session_id']}`, node {item['node_id']})_{warnings}"
        )
    lines += ["", "## Dropped", ""]
    for item in report["dropped_items"]:
        lines.append(
            f"- `{'; '.join(item['reasons'])}` — {item['preview']} "
            f"_(session `{item['session_id']}`, node {item['node_id']})_"
        )
    if report["written"]:
        lines += ["", "## Written", ""]
        lines += [f"- `{p}`" for p in report["written"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], out_dir: str | Path) -> Path:
    """Write ``REPORT.md`` inside ``out_dir``; returns the path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "REPORT.md"
    target.write_text(render_markdown(report), encoding="utf-8")
    return target
