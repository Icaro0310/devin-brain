<div align="center">

<img src="assets/banner.svg" alt="devin-memory" width="100%"/>

</div>

# devin-memory

> **Unofficial community project.** Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.

**[Português (BR)](README.pt-BR.md)** · English

An anti-poisoning memory store for Devin: durable facts with provenance,
versioning, and a quarantine gate — so agent memory can't be silently
corrupted by a bad session or injected content.

## The problem

Agent memory is a poisoning vector. Any tool that persists "facts" between
sessions can be corrupted by a single bad session — an injected instruction
or a pasted secret becomes a trusted belief in every future session, with no
review step and no way to answer *"where did this come from?"*.

## Prior art

- The **Devin memory MCP** (`retain`/`recall`/`reflect` over
  `.devin/memory/memories.jsonl`) — append-only, no screening, no session
  provenance. `devin-memory` exports to that exact line shape.
- **MemGPT / LangChain memory** — persistence layers that optimize for
  recall, not for auditing or distrusting what was stored.

`devin-memory` adapts the memory-store idea; it adds the parts those tools
don't have: a quarantine gate and provenance back to real session rows.

## What makes it Devin-native

1. **Side-by-side:** every entry can carry `source_session_id` +
   `source_rowid`, auditable against Devin's `sessions.db` via
   `devin-internals`' read-only store — the memory MCP cannot verify that a
   claimed source session (or a specific message row) ever existed. The
   quarantine gate also screens every write for secret and injection shapes.
2. **No-Devin:** without `sessions.db` there is no session provenance to
   audit — the extra disappears.
3. **One sentence:** *it's a memory store that remembers where each memory
   came from — and quarantines suspicious ones until a human releases them.*

## Install

Python ≥ 3.10 and `pipx` are required. **Windows (PowerShell):** install `pipx` with `py -m pip install --user pipx`, run `py -m pipx ensurepath`, then reopen the terminal. **Linux (Debian/Ubuntu):** run `sudo apt install pipx python3-venv` and `pipx ensurepath`; reopen the terminal. Other Linux distributions should install `pipx` using their package manager.

```bash
pipx install "devin-memory @ git+https://github.com/Icaro0310/devin-memory.git"
```

For development:

```bash
pip install -e ".[dev]"
pytest
```

## Usage

```bash
# Store a fact (screened on write; suspect content lands in quarantine)
devin-memory retain "CI is green on Windows + Linux" --tags ci,status
devin-memory retain "..." --source-session <session-id> --source-rowid <n>

# Keyword-ranked recall — returns active entries only
devin-memory recall "ci status" [--json] [--limit 5] [--tags a,b]

# Review and release quarantined entries
devin-memory quarantine                 # list with reasons
devin-memory quarantine --release <id>  # human override -> active

# Versioning and housekeeping
devin-memory supersede <id> "corrected fact"
devin-memory retract <id>
devin-memory list [--status active|quarantined|retracted] [--json]

# Audit an entry's provenance against a real sessions.db (read-only)
devin-memory verify <id> --sessions-db path/to/sessions.db

# Export active memories to a memory-MCP-compatible JSONL
devin-memory export --out memories.jsonl
```

## Learn from sessions with `devin-learning`

This companion CLI extracts candidate lessons from a `sessions.db` and writes
reviewable skill drafts. It does not install drafts into a workspace by default.

```bash
devin-learning extract --sessions-db path/to/sessions.db --out ./learning-drafts
devin-learning review --out ./learning-drafts

# After reviewing drafts, explicitly allow output to a live skill directory:
devin-learning extract --sessions-db path/to/sessions.db --out .devin/skills --apply
```

`review` is a dry-run unless `--apply` is given; `review --apply` moves rejected
drafts under `_rejected/`. The extractor reads session contents, so keep its
output private until reviewed.

The store is `./memory.db` by default — override with `--db` or
`DEVIN_MEMORY_DB`. It is the only store this tool writes to; Devin's
`sessions.db`, `acp-messages/*.db` and `state.vscdb` are only ever read.

## Works with Devin alone (Devin-only mode)

devin-memory keeps a local memory store (JSONL) with provenance tracking and
a quarantine lane — no external memory service, no network calls. Both console
scripts (`devin-memory` and `devin-learning`) run on your machine only.

Honest caveat: write-time screening is a heuristic, not a guarantee — suspect
entries land in quarantine for **human review**, so keep that habit.

## Platform support

The memory store uses an explicit local SQLite path and the session database is
provided with `--sessions-db`; no platform-specific path is assumed. Windows
and Linux are supported and covered by CI.

## Limitations

- **M1 is a primitive — no auto-extraction yet.** `retain` stores what it is
  told; turning sessions into memories is M2 (`devin-learning` pipeline).
- **The screen is a filter, not a guarantee.** Pattern-based secret detection
  and injection heuristics have both false positives (→ quarantine, one
  command to release) and false negatives. Run dedicated scanners
  (gitleaks, `devin-redact`) too — this complements them.
- **Recall ranking is keyword-based**, deterministic and documented — no
  embeddings or semantic search in M1.
- **Provenance is recorded, not self-verifying.** `retain` stores the
  claimed `source_session_id`/`source_rowid`; `verify` audits it against a
  real `sessions.db` afterwards. A bad actor can claim fake provenance —
  the point is that it is *checkable*.
- **Quarantined supersessions still retire the old version.** If the
  replacement quarantines, review the queue (`quarantine --release`).
- **Not on PyPI yet** — install from the repo for now.

## License

MIT — see [LICENSE](LICENSE).
