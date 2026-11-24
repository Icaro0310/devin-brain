"""Public read API + consumer integrations for the task ledger.

Consumers (devin-assure, devin-explore, this package's memory ingest)
should use :class:`Ledger` and these functions — never parse
``ledger.jsonl`` themselves.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from devin_memory.ledger import core, storage

OPEN_STATES = ("queued", "active", "parked", "blocked")


@dataclass(frozen=True)
class Task:
    """One folded ledger task (the dict core.load() produces)."""

    id: str
    title: str
    status: str
    raw: dict

    def __getattr__(self, name: str):
        return self.raw.get(name)


@dataclass(frozen=True)
class Handoff:
    id: str
    path: Path


class Ledger:
    """Handle bound to a ledger directory (default: XDG store)."""

    def __init__(self, path: str | Path | None = None):
        self.dir = Path(path) if path else storage.ledger_dir()

    @contextmanager
    def _env(self) -> Iterator[None]:
        old = os.environ.get("DEVIN_LEDGER_DIR")
        os.environ["DEVIN_LEDGER_DIR"] = str(self.dir)
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("DEVIN_LEDGER_DIR", None)
            else:
                os.environ["DEVIN_LEDGER_DIR"] = old

    def tasks(self) -> dict[str, dict]:
        """All folded tasks keyed by id (empty dict when no ledger)."""
        with self._env():
            return core.load()

    def task_list(self) -> list[Task]:
        return [Task(id=tid, title=str(t.get("title", "")),
                     status=str(t.get("status", "")), raw=t)
                for tid, t in sorted(self.tasks().items())]

    def open_tasks(self) -> list[Task]:
        return [t for t in self.task_list() if t.status in OPEN_STATES]

    def parked(self, older_than_days: float | None = None) -> list[Task]:
        out = []
        for t in self.open_tasks():
            if t.status != "parked":
                continue
            if older_than_days is not None:
                upd = t.raw.get("updated") or t.raw.get("created") or ""
                try:
                    from devin_memory.ledger.core import age_hours
                    if age_hours(str(upd)) / 24 < older_than_days:
                        continue
                except Exception:
                    pass
            out.append(t)
        return out

    def handoff_for(self, task_id: str) -> Handoff | None:
        p = self.dir / "handoffs" / f"{task_id}.md"
        return Handoff(id=task_id, path=p) if p.exists() else None


def _tasks_of(ledger: Ledger | Path | str) -> dict[str, dict]:
    if isinstance(ledger, Ledger):
        return ledger.tasks()
    return Ledger(ledger).tasks()


def audit(ledger: Ledger | Path | str, parked_days: int = 7) -> dict:
    """Consumer surface for devin-assure: open-loop health snapshot."""
    tasks = _tasks_of(ledger)
    now_open = {"queued": 0, "active": 0, "parked": 0, "blocked": 0}
    parked_overdue: list[dict] = []
    blocked: list[dict] = []
    active: list[dict] = []
    for tid, t in tasks.items():
        st = t.get("status", "")
        if st in now_open:
            now_open[st] += 1
        row = {"id": tid, "title": t.get("title", ""), "status": st,
               "updated": t.get("updated", "")}
        if st == "active":
            active.append(row)
        elif st == "blocked":
            blocked.append(row)
        elif st == "parked":
            upd = str(t.get("updated") or "")
            try:
                from devin_memory.ledger.core import age_hours
                age_d = age_hours(upd) / 24 if upd else 0
            except Exception:
                age_d = 0
            if age_d >= parked_days:
                row["age_days"] = round(age_d, 1)
                parked_overdue.append(row)
    return {
        "counts": now_open,
        "total": len(tasks),
        "parked_overdue": parked_overdue,
        "blocked": blocked,
        "active": active,
        "parked_days_threshold": parked_days,
    }


def check(ledger: Ledger | Path | str) -> tuple[bool, list[str]]:
    """Consumer surface for devin-explore doctor: (healthy, problems)."""
    d = ledger.dir if isinstance(ledger, Ledger) else Path(ledger)
    problems: list[str] = []
    lf = d / "ledger.jsonl"
    if lf.exists():
        try:
            with open(lf, "rb") as f:
                for i, line in enumerate(f, 1):
                    if line.strip():
                        json.loads(line)
        except Exception as e:
            problems.append(f"ledger.jsonl corrupt at line {i}: {e}")
            return False, problems
    tasks = _tasks_of(ledger)
    for tid, t in tasks.items():
        st = t.get("status")
        if st in ("active", "parked"):
            if not (d / "handoffs" / f"{tid}.md").exists():
                problems.append(f"{tid} [{st}] has no handoff file")
    return (not problems), problems


def stats_dir(d: Path) -> dict:
    """Counts by status + file stats for `devin-memory ledger stats`."""
    a = audit(d)
    sessions = handoffs = 0
    sf = d / "sessions.jsonl"
    if sf.exists():
        with open(sf, "rb") as f:
            sessions = sum(1 for l in f if l.strip())
    hd = d / "handoffs"
    if hd.is_dir():
        handoffs = len(list(hd.glob("*.md")))
    return {
        "dir": str(d),
        "counts": a["counts"],
        "total_tasks": a["total"],
        "sessions": sessions,
        "handoffs": handoffs,
        "ledger_exists": (d / "ledger.jsonl").exists(),
    }


def check_dir(d: Path) -> tuple[bool, list[str]]:
    return check(Ledger(d))


def export_facts(ledger: Ledger | Path | str) -> list[dict]:
    """Done tasks as ingestible facts for devin-memory."""
    facts = []
    for tid, t in _tasks_of(ledger).items():
        if t.get("status") != "done":
            continue
        facts.append({
            "id": tid,
            "title": str(t.get("title", "")),
            "evidence": str(t.get("evidence", "")),
            "completed": str(t.get("updated", "")),
            "acceptance": list(t.get("accept") or []),
        })
    return facts
