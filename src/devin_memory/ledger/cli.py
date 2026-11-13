"""``devin-memory ledger`` — domain CLI: new commands here, the original
task-ledger command set delegated to :mod:`devin_memory.ledger.core`.

New commands: ``init``, ``migrate``, ``doctor``, ``hook``, ``stats``.
Everything else (``add``, ``start``, ``park``, ``done``, ``list``,
``prime``, ``check`` …) is forwarded unchanged to core's parser, so the
skill/hook contract and all migrated tests keep working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from devin_memory.ledger import core, hooks, integrations, migrate, storage

NEW_COMMANDS = {"init", "migrate", "doctor", "hook", "stats"}


def _cmd_init(_a) -> int:
    d = storage.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "handoffs").mkdir(exist_ok=True)
    (d / "evidence").mkdir(exist_ok=True)
    print(f"ledger dir: {d}")
    print(f"ledger file: {storage.ledger_file()}")
    return 0


def _cmd_migrate(a) -> int:
    src = Path(a.from_dir).expanduser()
    if not src.is_dir():
        print(f"ledger: no such directory: {src}", file=sys.stderr)
        return 2
    dst = storage.ledger_dir()
    try:
        rep = migrate.migrate_legacy(src, dst)
    except migrate.MigrateError as e:
        print(f"ledger migrate: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2))
    return 0


def _cmd_doctor(_a) -> int:
    problems: list[str] = []
    d = storage.ledger_dir()
    lf = storage.ledger_file()
    if not d.is_dir():
        problems.append(f"ledger dir missing: {d} (run: devin-memory ledger init)")
    else:
        if lf.exists():
            try:
                with open(lf, "rb") as f:
                    for i, line in enumerate(f, 1):
                        if line.strip():
                            json.loads(line)
            except Exception as e:
                problems.append(f"{lf.name}: corrupt at line {i}: {e}")
        else:
            print(f"note: {lf} does not exist yet (empty ledger)")
        for sub in ("handoffs", "evidence"):
            if not (d / sub).is_dir():
                problems.append(f"{sub}/ missing under {d}")
    ok, issues = integrations.check_dir(d) if d.is_dir() else (False, ["no dir"])
    problems.extend(issues)
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print("doctor: ok")
    return 1 if problems else 0


def _cmd_hook(a) -> int:
    import sys as _sys
    payload = hooks.read_payload()
    return hooks.handle(a.event, payload)


def _cmd_stats(_a) -> int:
    d = storage.ledger_dir()
    rep = integrations.stats_dir(d)
    print(json.dumps(rep, indent=2, sort_keys=True))
    return 0


def _new_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="devin-memory ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the ledger directory layout")
    p = sub.add_parser("migrate", help="import a legacy ~/.devin/ledger")
    p.add_argument("--from-dir", required=True, metavar="PATH")
    sub.add_parser("doctor", help="health-check the ledger store")
    p = sub.add_parser("hook", help="run a lifecycle hook event "
                       "(session-start|user-prompt|stop|session-end)")
    p.add_argument("event")
    sub.add_parser("stats", help="counts by status + sessions/handoffs")
    return ap


def _new_main(args: list[str]) -> int:
    a = _new_parser().parse_args(args)
    return {
        "init": _cmd_init,
        "migrate": _cmd_migrate,
        "doctor": _cmd_doctor,
        "hook": _cmd_hook,
        "stats": _cmd_stats,
    }[a.cmd](a)


def main(argv: list[str] | None = None) -> int:
    """Entry for ``devin-memory ledger ...`` — argv excludes 'ledger'."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in NEW_COMMANDS:
        return _new_main(args)
    rc = core.main(args)
    return 0 if rc is None else rc  # core cmd_* print, they don't return ints


if __name__ == "__main__":
    sys.exit(main())
