"""``devin-memory`` — thin CLI wrapper; all logic lives in the library.

Subcommands:

- ``retain "<content>" [--tags a,b] [--workspace PATH]``
  ``[--source-session ID] [--source-rowid N]``
- ``recall "<query>" [--limit N] [--tags a,b] [--json]``
- ``quarantine [<id>] [--reason r] [--list] [--release ID] [--json]``
- ``conflicts [--json]`` — contradiction pairs linked at retain time
- ``extract <session-id|--latest> --sessions-db DB [--auto-approve]``
- ``approve <id>`` — promote a proposed extraction to active
- ``prime [--workspace PATH] [--max-tokens N]`` — hook context block
- ``retract <id>`` · ``supersede <id> "<content>"`` · ``list``
- ``export --out memories.jsonl [--all]``
- ``verify <id> --sessions-db <sessions.db>``

The DB is ``./memory.db`` by default — override with the global ``--db``
flag or the ``DEVIN_MEMORY_DB`` env var. This CLI only ever writes to its
own ``memory.db``; Devin's stores are read through devin-internals and
never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from devin_internals.schema import SchemaError

from devin_memory import ops
from devin_memory.export import export_jsonl
from devin_memory.store import Entry, MemoryStore

DEFAULT_DB = "memory.db"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def _fmt_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max([len(h), *(len(r[i]) for r in rows)])
        for i, h in enumerate(headers)
    ]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(r[i].ljust(widths[i]) for i in range(len(headers)))
        for r in rows
    ]
    return "\n".join([line, sep, *body])


def _truncate(text: str, width: int) -> str:
    text = " ".join(text.splitlines())
    return text if len(text) <= width else text[: width - 1] + "…"


def _tags_arg(raw: str | None) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()] if raw else []


def _open_store(args: argparse.Namespace) -> MemoryStore:
    return MemoryStore(args.db)


def _entry_rows(entries: list[Entry]) -> list[list[str]]:
    return [
        [
            str(e.id),
            e.status,
            f"v{e.version}",
            ",".join(e.tags) or "-",
            ",".join(e.quarantine_reasons) or "-",
            _truncate(e.content, 60),
        ]
        for e in entries
    ]


_ENTRY_HEADERS = ["ID", "STATUS", "VER", "TAGS", "REASONS", "CONTENT"]


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------


def cmd_retain(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        entry = ops.retain(
            store,
            args.content,
            tags=_tags_arg(args.tags),
            source_session_id=args.source_session,
            source_rowid=args.source_rowid,
            workspace=args.workspace,
        )
    if args.json:
        _print_json(entry.to_dict())
    else:
        line = f"id={entry.id} status={entry.status}"
        if entry.quarantine_reasons:
            line += f" reasons=[{', '.join(entry.quarantine_reasons)}]"
        if entry.conflicts_with is not None:
            line += f" conflicts={entry.conflicts_with}"
        print(line)
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        hits = ops.recall(
            store, args.query, limit=args.limit, tags=_tags_arg(args.tags) or None
        )
    if args.json:
        _print_json([e.to_dict() for e in hits])
    elif hits:
        rows = [
            [str(e.id), ",".join(e.tags) or "-", _truncate(e.content, 72)]
            for e in hits
        ]
        print(_fmt_table(["ID", "TAGS", "CONTENT"], rows))
    else:
        print("no memories")
    return 0


def cmd_quarantine(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        if args.release is not None:
            entry = ops.release(store, args.release)
            if args.json:
                _print_json(entry.to_dict())
            else:
                print(f"id={entry.id} status={entry.status}")
            return 0
        if args.id is not None:
            entry = ops.quarantine_entry(
                store, args.id, reason=args.reason or "manual:user"
            )
            if args.json:
                _print_json(entry.to_dict())
            else:
                print(
                    f"id={entry.id} status={entry.status}"
                    f" reasons=[{', '.join(entry.quarantine_reasons)}]"
                )
            return 0
        entries = ops.list_entries(store, status="quarantined")
    if args.json:
        _print_json([e.to_dict() for e in entries])
    elif entries:
        print(_fmt_table(_ENTRY_HEADERS, _entry_rows(entries)))
    else:
        print("quarantine is empty")
    return 0


def cmd_retract(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        entry = ops.retract(store, args.id)
    print(f"id={entry.id} status={entry.status}")
    return 0


def cmd_supersede(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        entry = ops.supersede(
            store, args.id, args.content, tags=_tags_arg(args.tags) or None
        )
    if args.json:
        _print_json(entry.to_dict())
    else:
        print(
            f"id={entry.id} status={entry.status} version={entry.version}"
            f" supersedes={entry.supersedes_id}"
        )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        entries = ops.list_entries(store, status=args.status, limit=args.limit)
    if args.json:
        _print_json([e.to_dict() for e in entries])
    elif entries:
        print(_fmt_table(_ENTRY_HEADERS, _entry_rows(entries)))
    else:
        print("no entries")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        n = export_jsonl(store, args.out, include_non_active=args.all)
    print(f"exported {n} entries -> {args.out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        report = ops.verify_provenance(store, args.id, args.sessions_db)
    _print_json(report)
    ok = (
        report["checked"]
        and report["session_found"]
        and report["rowid_found"] is not False
    )
    return 0 if ok else 1


def cmd_conflicts(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        pairs = ops.conflicts(store)
    if args.json:
        _print_json(
            [
                {"newer": new.to_dict(), "older": old.to_dict()}
                for new, old in pairs
            ]
        )
    elif pairs:
        rows = [
            [
                str(new.id),
                str(old.id),
                _truncate(new.content, 38),
                _truncate(old.content, 38),
            ]
            for new, old in pairs
        ]
        print(_fmt_table(["NEW_ID", "OLD_ID", "NEW", "EXISTING"], rows))
    else:
        print("no conflicts")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        report = ops.extract_session(
            store,
            args.sessions_db,
            session_id=args.session_id,
            latest=args.latest,
            auto_approve=args.auto_approve,
        )
    if args.json:
        _print_json(report)
    else:
        counts = {"proposed": 0, "active": 0, "quarantined": 0}
        for item in report["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        print(
            f"session={report['session_id']}"
            f" scanned={report['nodes_scanned']}"
            f" candidates={report['candidates']}"
        )
        print(
            f"  proposed={counts.get('proposed', 0)}"
            f" active={counts.get('active', 0)}"
            f" quarantined={counts.get('quarantined', 0)}"
            f" duplicates={report['skipped_duplicates']}"
        )
        print(
            "  review with: devin-memory list --status proposed"
            "  /  approve <id>"
        )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        entry = ops.approve(store, args.id)
    if args.json:
        _print_json(entry.to_dict())
    else:
        print(f"id={entry.id} status={entry.status}")
    return 0


def cmd_prime(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        text = ops.prime(
            store,
            workspace=args.workspace,
            max_tokens=args.max_tokens,
        )
    print(text, end="")
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devin-memory",
        description=(
            "Anti-poisoning memory store: durable facts with provenance, "
            "versioning, and a quarantine gate."
        ),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("DEVIN_MEMORY_DB", DEFAULT_DB),
        help="path to memory.db (default: ./memory.db or $DEVIN_MEMORY_DB)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("retain", help="screen and store a memory")
    p.add_argument("content", help="the fact/lesson to remember")
    p.add_argument("--tags", metavar="a,b", help="comma-separated tags")
    p.add_argument("--workspace", metavar="PATH",
                   help="scope this memory to a workspace (default: global)")
    p.add_argument("--source-session", metavar="ID",
                   help="Devin session id this memory came from")
    p.add_argument("--source-rowid", type=int, metavar="N",
                   help="message_nodes rowid the fact is evidenced by")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_retain)

    p = sub.add_parser("recall", help="keyword-ranked recall (active only)")
    p.add_argument("query", help="free-text query; '' returns most recent")
    p.add_argument("--limit", type=int, default=5, metavar="N")
    p.add_argument("--tags", metavar="a,b", help="restrict to these tags")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_recall)

    p = sub.add_parser(
        "quarantine",
        help="list quarantined / mark an entry / release one",
    )
    p.add_argument("id", type=int, nargs="?", metavar="ID",
                   help="mark an existing entry as quarantined")
    p.add_argument("--reason", metavar="R",
                   help="quarantine reason stored for audit"
                        " (default: manual:user)")
    p.add_argument("--list", action="store_true", help="list (default action)")
    p.add_argument("--release", type=int, metavar="ID",
                   help="move a quarantined entry back to active")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_quarantine)

    p = sub.add_parser("retract", help="withdraw an entry (kept for history)")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_retract)

    p = sub.add_parser("supersede", help="replace an entry with a new version")
    p.add_argument("id", type=int)
    p.add_argument("content", help="the corrected content")
    p.add_argument("--tags", metavar="a,b",
                   help="tags for the new version (default: inherit)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_supersede)

    p = sub.add_parser("list", help="list entries")
    p.add_argument(
        "--status",
        choices=["active", "proposed", "quarantined", "retracted"],
    )
    p.add_argument("--limit", type=int, metavar="N")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("export", help="dump active memories to memories.jsonl")
    p.add_argument("--out", required=True, metavar="PATH",
                   help="output file (memory-MCP-compatible JSONL)")
    p.add_argument("--all", action="store_true",
                   help="include quarantined and retracted entries")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser(
        "verify", help="audit an entry's provenance against a sessions.db"
    )
    p.add_argument("id", type=int)
    p.add_argument("--sessions-db", required=True, metavar="PATH",
                   help="path to a Devin sessions.db")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser(
        "conflicts",
        help="list retain-time contradiction pairs (supersedes kept both)",
    )
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_conflicts)

    p = sub.add_parser(
        "extract",
        help="mine a session for durable knowledge -> proposed entries",
    )
    p.add_argument("session_id", nargs="?", metavar="SESSION_ID",
                   help="session to scan (or use --latest)")
    p.add_argument("--latest", action="store_true",
                   help="scan the most recently active session")
    p.add_argument("--sessions-db", required=True, metavar="PATH",
                   help="path to a Devin sessions.db (read-only)")
    p.add_argument("--auto-approve", action="store_true",
                   help="store clean candidates as active (default: proposed)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser(
        "approve", help="promote a proposed extraction to active"
    )
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser(
        "prime",
        help="print a compact recalled-context block (UserPromptSubmit hook)",
    )
    p.add_argument("--workspace", metavar="PATH",
                   help="only prime global + this-workspace memories")
    p.add_argument("--max-tokens", type=int,
                   default=ops.PRIME_DEFAULT_MAX_TOKENS, metavar="N",
                   help="size bound; ~4 chars/token estimate"
                        f" (default: {ops.PRIME_DEFAULT_MAX_TOKENS})")
    p.set_defaults(func=cmd_prime)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ops.MemoryOpsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
