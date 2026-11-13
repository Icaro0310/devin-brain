"""Import a legacy ``~/.devin/ledger`` directory into the XDG store.

Copy-only migration: the ledger is an append-only event log, so copying
``ledger.jsonl`` / ``sessions.jsonl`` / ``handoffs/`` / ``evidence/``
preserves every task id, session marker and handoff byte-for-byte.
Nothing is rewritten, merged or dropped — a non-empty destination
``ledger.jsonl`` refuses the import (fail closed, no silent merge).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


class MigrateError(Exception):
    pass


_COPY_FILES = ("ledger.jsonl", "sessions.jsonl", ".stop-guard.json")
_COPY_DIRS = ("handoffs", "evidence")


def _count_tasks(ledger_jsonl: Path) -> int:
    ids = set()
    with open(ledger_jsonl, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = ev.get("id")
            if isinstance(tid, str) and tid.startswith("DL-"):
                ids.add(tid)
    return len(ids)


def migrate_legacy(src: Path, dst: Path) -> dict:
    src = Path(src)
    dst = Path(dst)
    src_ledger = src / "ledger.jsonl"
    if not src_ledger.exists():
        raise MigrateError(f"{src}: no ledger.jsonl — nothing to migrate")
    dst_ledger = dst / "ledger.jsonl"
    if dst_ledger.exists() and dst_ledger.stat().st_size > 0:
        raise MigrateError(
            f"{dst_ledger} already has events — refusing to merge "
            "(migrate into an empty store or move the old one aside)")

    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in _COPY_FILES:
        s = src / name
        if s.exists():
            shutil.copy2(s, dst / name)
            copied.append(name)
    for name in _COPY_DIRS:
        s = src / name
        if s.is_dir():
            shutil.copytree(s, dst / name, dirs_exist_ok=True)
            copied.append(name + "/")

    sessions = 0
    sf = dst / "sessions.jsonl"
    if sf.exists():
        with open(sf, "rb") as f:
            sessions = sum(1 for l in f if l.strip())
    handoffs = len(list((dst / "handoffs").glob("*.md"))) if (dst / "handoffs").is_dir() else 0

    return {
        "from": str(src),
        "to": str(dst),
        "tasks": _count_tasks(dst_ledger),
        "sessions": sessions,
        "handoffs": handoffs,
        "copied": copied,
    }
