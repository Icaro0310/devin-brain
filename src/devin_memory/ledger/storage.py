"""XDG path resolution for the task ledger — single source of truth.

Precedence: ``$DEVIN_LEDGER_DIR`` (tests/hooks override) >
``$XDG_STATE_HOME/devin-memory/ledger`` > ``~/.local/state/devin-memory/ledger``.

The legacy location ``~/.devin/ledger`` is imported once by
``devin-memory ledger migrate --from-dir``; nothing here reads it
implicitly. (No module-level ``Path.home()`` — it raises when HOME is
unset, e.g. stripped-env CI subprocesses.)
"""

from __future__ import annotations

import os
from pathlib import Path


def ledger_dir() -> Path:
    env = os.environ.get("DEVIN_LEDGER_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "devin-memory" / "ledger"


def ledger_file() -> Path:
    return ledger_dir() / "ledger.jsonl"


def sessions_file() -> Path:
    return ledger_dir() / "sessions.jsonl"


def guard_file() -> Path:
    return ledger_dir() / ".stop-guard.json"


def handoffs_dir() -> Path:
    return ledger_dir() / "handoffs"


def evidence_dir() -> Path:
    return ledger_dir() / "evidence"
