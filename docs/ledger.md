# Task ledger (`devin-memory ledger`)

Persistent, append-only tracker of tasks and open loops — migrated into
`devin-memory` 0.4.0 from the standalone `task-ledger` skill
(`~/.devin/skills/task-ledger`). Stdlib only, no network.

Core idea: **finishing is the unit of progress**. One active task at a
time; every task ends `done` (with evidence), `parked` (with a next
step), `blocked` (with a reason) or `dropped` (with a reason). Nothing
disappears silently.

## Install / storage

```bash
pip install devin-memory        # ledger included, zero extra deps
devin-memory ledger init         # creates the XDG store
```

Store location (first match wins):

1. `$DEVIN_LEDGER_DIR` — explicit override (tests, hooks)
2. `$XDG_STATE_HOME/devin-memory/ledger`
3. `~/.local/state/devin-memory/ledger`

Layout: `ledger.jsonl` (append-only event log, folded on read),
`sessions.jsonl` (hook lifecycle markers), `handoffs/<id>.md`,
`evidence/`, `.stop-guard.json`.

## Commands

The original task-ledger command set is unchanged:

```bash
devin-memory ledger add "title" --accept "done when..." [--accept ...]
devin-memory ledger start|park|block|done|drop|adopt|reopen|handoff ID
devin-memory ledger list [--all] [--json] · ready · digest · prime
devin-memory ledger check [--closing] · audit · catchup · export · snippet
devin-memory ledger identify · annotate
```

Domain additions:

```bash
devin-memory ledger init      # create store layout
devin-memory ledger stats     # counts by status + sessions/handoffs
devin-memory ledger doctor    # health check (jsonl parse, handoffs, dirs)
devin-memory ledger migrate --from-dir ~/.devin/ledger
devin-memory ledger hook <session-start|user-prompt|stop|session-end>
```

Exit codes: `0` ok, `1` rule violation, `2` usage/data error. Corrupt
ledger fails closed — never repaired silently.

## Lifecycle hooks

Wire in `~/.config/devin/config.json` under `hooks.<Event>[].hooks[]`:

```json
{"command": "devin-memory ledger hook session-start"}
```

| Event | Behavior |
|---|---|
| `session-start` | records session, injects `prime` context (+ rule only when work is active) |
| `user-prompt` | one-line reminder when a task is active (data, not instructions) |
| `stop` | `check --closing`; blocks ≤3×/session then escalates to `blocked-attempts` |
| `session-end` | records session end for orphan forensics |

Hooks are fail-open: handled failures exit 0 silently; unexpected
crashes exit 2.

## Migration from `~/.devin/ledger`

```bash
devin-memory ledger migrate --from-dir ~/.devin/ledger
```

Copy-only: `ledger.jsonl`, `sessions.jsonl`, `handoffs/`, `evidence/`
are copied byte-for-byte — every `DL-xxxx` id, session marker and
handoff is preserved. Refuses to run into a non-empty destination
(fail closed, no silent merge). Afterwards the legacy skill directory
can be retired (`~/.devin/skills/task-ledger` → `.task-ledger.old`).

## Python API (consumers)

```python
from devin_memory.ledger import Ledger
from devin_memory.ledger.integrations import audit, check, export_facts

ledger = Ledger()                       # XDG store (or Ledger(path))
tasks = ledger.tasks()                   # folded dict keyed by id
parked = ledger.parked(older_than_days=7)

audit(ledger, parked_days=7)            # -> devin-assure ledger-audit
check(ledger)                           # -> (bool, problems) for doctor
export_facts(ledger)                    # done tasks -> memory ingest facts
```

`devin-assure` exposes this as `devin-assure ledger-audit` (optional
extra `devin-assure[ledger]`); `devin-explore` doctor checks it via
`devin-explore doctor --check ledger`.
