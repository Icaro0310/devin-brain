"""Thin CLI wrapper — all logic lives in the library modules."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from devin_internals.schema import SchemaError

from . import __version__
from .extract import extract_candidates
from .report import build_report, render_markdown, write_report
from .review import review_candidates, review_text
from .skills import LiveSkillsDirError, emit_drafts


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
    try:
        candidates = extract_candidates(args.sessions_db)
        verdicts = review_candidates(candidates)
        written = emit_drafts(verdicts, args.out, apply=args.apply)
    except (SchemaError, LiveSkillsDirError, OSError) as exc:
        print(f"devin-learning: {exc}", file=sys.stderr)
        return 3
    report = build_report(args.sessions_db, verdicts, written=written)
    report_path = write_report(report, args.out)
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
    if args.command == "review":
        return _cmd_review(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
