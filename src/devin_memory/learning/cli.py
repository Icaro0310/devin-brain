"""Thin CLI wrapper — all logic lives in the library modules."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from devin_internals.schema import SchemaError

from . import __version__
from .extract import extract_candidates, scan_watermark
from .report import build_report, render_markdown, write_report
from .review import review_candidates, review_text
from .skills import LiveSkillsDirError, emit_drafts
from .weekly import build_weekly, write_weekly_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devin-learning",
        description="Extract durable lessons from Devin sessions into "
        "reviewable SKILL.md drafts — with an anti-poisoning safety gate "
        "(unofficial).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    extract_p = sub.add_parser(
        "extract", help="scan sessions.db and emit learned-<topic>/SKILL.md drafts"
    )
    extract_p.add_argument(
        "--sessions-db", type=Path, required=True, help="path to Devin's sessions.db"
    )
    extract_p.add_argument(
        "--out", type=Path, required=True, help="directory for drafts + REPORT.md"
    )
    extract_p.add_argument(
        "--json", action="store_true", help="print the JSON report to stdout"
    )
    extract_p.add_argument(
        "--apply",
        action="store_true",
        help="allow --out to be a live .devin/skills directory",
    )
    extract_p.add_argument(
        "--since",
        type=int,
        default=0,
        metavar="EPOCH_MS",
        help="skip message nodes created at or before this timestamp "
        "(milliseconds, watermark filter)",
    )
    extract_p.add_argument(
        "--incremental",
        action="store_true",
        help="watermark mode via the shared cursor "
        "(.devin/devin-learning-extract-state.json): extract only nodes "
        "newer than the last committed run, then advance the watermark",
    )

    weekly_p = sub.add_parser(
        "weekly-report",
        help="emit a public-safe weekly summary (weekly-YYYY-Www.md) — "
        "aggregate counts only, no session text or paths",
    )
    weekly_p.add_argument(
        "--sessions-db", type=Path, required=True, help="path to Devin's sessions.db"
    )
    weekly_p.add_argument(
        "--out", type=Path, required=True, help="directory for weekly-*.md reports"
    )
    weekly_p.add_argument(
        "--json", action="store_true", help="print the JSON report to stdout"
    )
    weekly_p.add_argument(
        "--since",
        type=int,
        default=None,
        metavar="EPOCH_MS",
        help="window floor override (milliseconds) — bypasses the cursor "
        "and the --days fallback",
    )
    weekly_p.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="window length in days used when the learning-weekly cursor "
        "has no committed watermark yet (default: 7)",
    )

    review_p = sub.add_parser(
        "review", help="re-review emitted drafts (dry-run by default)"
    )
    review_p.add_argument("--out", type=Path, required=True, help="drafts directory")
    review_p.add_argument(
        "--json", action="store_true", help="print the JSON report to stdout"
    )
    review_p.add_argument(
        "--apply",
        action="store_true",
        help="quarantine rejected drafts into <out>/_rejected/",
    )
    return parser


def _cmd_extract(args: argparse.Namespace) -> int:
    cursor = None
    if args.incremental:
        from devin_internals.cursor import Cursor

        cursor = Cursor("devin-learning-extract")
    since = args.since or (cursor.get("last_node_at", 0) if cursor else 0)
    try:
        # Bound the scan before reading candidates: a node inserted during
        # extraction gets a timestamp above this watermark and is picked up
        # by the next incremental run instead of being skipped forever.
        watermark = scan_watermark(args.sessions_db) if cursor is not None else 0
        candidates = extract_candidates(args.sessions_db, since=since)
        verdicts = review_candidates(candidates)
        written = emit_drafts(verdicts, args.out, apply=args.apply)
    except (SchemaError, LiveSkillsDirError, OSError) as exc:
        print(f"devin-learning: {exc}", file=sys.stderr)
        return 3
    report = build_report(args.sessions_db, verdicts, written=written)
    report_path = write_report(report, args.out)
    if cursor is not None:
        # Commit only after the report is on disk — a failed run leaves the
        # watermark untouched so a retry reproduces the same output.
        cursor.set("last_node_at", max(watermark, since))
        cursor.commit()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(
            f"{report['candidates']} candidate(s): "
            f"{report['accepted']} accepted, {report['dropped']} dropped"
        )
        for p in written:
            print(f"  wrote {p}")
        print(f"  report {report_path}")
    return 0


def _cmd_weekly(args: argparse.Namespace) -> int:
    from devin_internals.cursor import Cursor

    cursor = Cursor("devin-learning-weekly")
    now_ms = int(time.time() * 1000)
    try:
        # Capture the watermark BEFORE the scan: anything appended while we
        # work is newer than it and gets re-scanned next week.
        watermark = scan_watermark(args.sessions_db)
        if args.since is not None:
            since = args.since
        else:
            since = cursor.get("last_node_at", 0) or max(
                0, now_ms - args.days * 86_400_000
            )
        candidates = extract_candidates(args.sessions_db, since=since)
        verdicts = review_candidates(candidates)
        report = build_weekly(verdicts, since_ms=since, until_ms=now_ms)
        report_path = write_weekly_report(report, args.out)
    except (SchemaError, OSError) as exc:
        print(f"devin-learning: {exc}", file=sys.stderr)
        return 3
    # Cursor commits AFTER the artifact is durable — a crash re-reports.
    cursor.set("last_node_at", max(watermark, since))
    cursor.set("last_report_week", report["week"])
    cursor.commit()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(
            f"weekly report {report['week']}: {report['candidates']} "
            f"candidate(s), {report['accepted']} accepted, "
            f"{report['dropped']} quarantined"
        )
        print(f"  wrote {report_path}")
    return 0


def _quarantine(path: Path, out_dir: Path) -> Path:
    target_dir = out_dir / "_rejected"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.parent.name}.md"
    shutil.move(str(path), target)
    return target


def _cmd_review(args: argparse.Namespace) -> int:
    drafts = sorted(args.out.glob("learned-*/SKILL.md"))
    if not drafts:
        print(
            f"devin-learning: no learned-*/SKILL.md drafts under {args.out}",
            file=sys.stderr,
        )
        return 3
    results = []
    for path in drafts:
        text = path.read_text(encoding="utf-8")
        reasons, warnings = review_text(text)
        results.append(
            {
                "path": str(path),
                "topic": path.parent.name.removeprefix("learned-"),
                "accepted": not reasons,
                "reasons": list(reasons),
                "warnings": list(warnings),
            }
        )
    rejected = [r for r in results if not r["accepted"]]
    if args.apply:
        for r in rejected:
            moved = _quarantine(Path(r["path"]), args.out)
            r["quarantined_to"] = str(moved)
    report = {
        "tool": "devin-learning",
        "version": __version__,
        "out_dir": str(args.out),
        "checked": len(results),
        "rejected": len(rejected),
        "dry_run": not args.apply,
        "drafts": results,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        for r in results:
            status = "ok" if r["accepted"] else "REJECTED"
            note = f" — {'; '.join(r['reasons'])}" if r["reasons"] else ""
            print(f"  {status} learned-{r['topic']}{note}")
        verb = "quarantined" if args.apply else "would be quarantined"
        print(f"{report['checked']} draft(s) checked, {len(rejected)} {verb}")
    return 1 if rejected else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "weekly-report":
        return _cmd_weekly(args)
    if args.command == "review":
        return _cmd_review(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
