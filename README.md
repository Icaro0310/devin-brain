<div align="center">

<img src="assets/banner.svg" alt="devin-memory" width="100%"/>

<a href="https://github.com/Icaro0310/devin-brain/actions/workflows/ci.yml"><img src="https://github.com/Icaro0310/devin-brain/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
<a href="https://pypi.org/project/devin-memory/"><img src="https://img.shields.io/pypi/v/devin-memory" alt="PyPI"/></a>
<a href="https://scorecard.dev/viewer/?uri=github.com/Icaro0310/devin-brain"><img src="https://api.scorecard.dev/projects/github.com/Icaro0310/devin-brain/badge" alt="OpenSSF Scorecard"/></a>
<a href="https://m8ven.ai/mcp/icaro0310-devin-memory-xgy2rx?s=readme"><img src="https://m8ven.ai/badge/mcp/icaro0310-devin-memory-xgy2rx" alt="M8ven Score"/></a>
<a href="https://glama.ai/mcp/servers/Icaro0310/devin-brain"><img src="https://glama.ai/mcp/servers/Icaro0310/devin-brain/badges/score.svg" alt="Glama Score"/></a>
<a href="https://mcpservers.org/servers/icaro0310/devin-memory"><img src="https://mcpservers.org/badge.svg" alt="Listed on mcpservers.org"/></a>
<a href="https://mcprush.com/to/devin-memory-mcp?ref=badge"><img src="https://mcprush.com/badge/devin-memory-mcp/score.svg" alt="mcprush Score"/></a>
<a href="https://registry.modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP_Registry-published-blueviolet" alt="MCP Registry"/></a>

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"/></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"/></a>
<a href="https://github.com/Icaro0310/devin-brain"><img src="https://img.shields.io/github/stars/Icaro0310/devin-brain" alt="GitHub stars"/></a>
<a href="https://github.com/Icaro0310/devin-brain/commits/main"><img src="https://img.shields.io/github/last-commit/Icaro0310/devin-brain" alt="Last commit"/></a>
<a href="https://github.com/Icaro0310/awesome-devin"><img src="https://img.shields.io/badge/part%20of-devin--*-ecosystem-7c3aed" alt="devin-* ecosystem"/></a>
<a href="https://github.com/Icaro0310/devin-brain/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs welcome"/></a>
</div>

<!-- DEVIN-ECO:BEGIN -->
> **Part of the [DEVIN ecosystem](https://github.com/Icaro0310/awesome-devin)**  
> Track: Build · Nature: product  
> For: AI engineers, Developers, Data Scientists  
> Interface: CLI / Python library / MCP server / Service  
> Path: AI engineers · step 3/3 — after `devin-orchestrator`
<!-- DEVIN-ECO:END -->

<!-- DEVIN-WHERE:BEGIN -->
## Where this fits

- **Job:** Build
- **Product:** [`devin-brain`](https://github.com/Icaro0310/devin-brain)
- **Packages:** `devin-memory`
- **Mode:** mixed
- **Foundation:** [`devin-internals-spec`](https://github.com/Icaro0310/devin-internals-spec)
- **Ecosystem:** [`awesome-devin`](https://github.com/Icaro0310/awesome-devin) · registry: [`devin-powerups`](https://github.com/Icaro0310/devin-powerups)
<!-- DEVIN-WHERE:END -->

# devin-memory

> **Renamed (Oct 2026):** this repository moved from `Icaro0310/devin-memory`
> to `Icaro0310/devin-brain` — the PyPI package, CLI commands and MCP server
> name stay `devin-memory`; stars, issues and history are preserved by the
> GitHub redirect.

> **Unofficial community project.** Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.

**[Linux](README.linux.md)** · **[Personal Windows](README.windows.md)** · **[Corporate Windows](README.corporate-windows.md)**

Part of the [awesome-devin](https://github.com/Icaro0310/awesome-devin) ecosystem: the curated hub for the devin-* tools.

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

Python ≥ 3.10 required; install with `uv` (recommended) or `pipx`.

```bash
uv tool install 'devin-memory[mcp]'
```

or with `pipx` (alternative):

```bash
pipx install 'devin-memory[mcp]'
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
devin-memory retain "..." --workspace /path/to/project   # scope to a workspace
devin-memory retain "..." --expires-at 2026-12-31T00:00:00Z  # TTL: drops
                                   # out of recall/prime after this instant

# Keyword-ranked recall — returns active, unexpired entries only;
# scores are weighted by recency decay so fresh memories outrank stale ones
devin-memory recall "ci status" [--json] [--limit 5] [--tags a,b]
devin-memory recall "ci status" --include-expired  # also surface expired

# Quarantine lane: list, mark an existing entry, or release one
devin-memory quarantine                          # list with reasons
devin-memory quarantine <id> [--reason manual:x] # mark entry as quarantined
devin-memory quarantine --release <id>           # human override -> active
devin-memory quarantine --digest [--json]        # audit hash (read-only)

# Contradictions: a conflicting retain is linked, not overwritten
devin-memory conflicts [--json]     # (newer, older) pairs; resolve with
                                    # supersede / retract / quarantine <id>

# Mine a session for durable knowledge -> proposed entries (inactive
# until reviewed); extraction is heuristic — see "Limitations"
devin-memory extract <session-id> --sessions-db path/to/sessions.db
devin-memory extract --latest --sessions-db path/to/sessions.db [--auto-approve]
devin-memory list --status proposed   # review queue
devin-memory approve <id>             # proposed -> active

# Context block for a UserPromptSubmit hook — active entries only,
# filtered by workspace + machine profile, bounded by ~4 chars/token
devin-memory prime [--workspace PATH] [--max-tokens N]

# Versioning and housekeeping
devin-memory supersede <id> "corrected fact" [--expires-at <iso>]
                                          # default: inherit old expiry
devin-memory retract <id>
devin-memory list [--status active|proposed|quarantined|retracted] [--json]
devin-memory compact [--json]   # dedup report (dry-run)
devin-memory compact --apply    # retract copies + vacuum the file

# Audit an entry's provenance against a real sessions.db (read-only)
devin-memory verify <id> --sessions-db path/to/sessions.db

# Export active memories to a memory-MCP-compatible JSONL
devin-memory export --out memories.jsonl
```

## MCP server

<!-- mcp-name: io.github.Icaro0310/devin-memory -->

`devin-memory` is also a real MCP server (stdio) — the same retain/recall
pipeline with the quarantine gate on every write, callable from Devin,
Claude Desktop, Cursor or any MCP client:

```bash
pipx install "devin-memory-mcp"
```

The `devin-memory-mcp` console script also ships inside the base
`devin-memory` dist, so a bare `uv tool install devin-memory` (no extra)
leaves a script that exits with `error: The MCP server needs the 'mcp'
extra` — recovery steps live in the Troubleshooting section of each
platform guide ([Linux](README.linux.md),
[Personal Windows](README.windows.md),
[Corporate Windows](README.corporate-windows.md)).

Client config:

```json
{
  "mcpServers": {
    "devin-memory": {
      "command": "devin-memory-mcp",
      "args": ["--db", "/path/to/memory.db"]
    }
  }
}
```

The same stdio server registers in other MCP hosts:

**Zed** — `context_servers` in `settings.json`:

```json
{
  "context_servers": {
    "devin-memory": {
      "command": { "path": "devin-memory-mcp", "args": ["--db", "/path/to/memory.db"] }
    }
  }
}
```

**JetBrains** — Settings → Tools → AI Assistant → Model Context Protocol → Add:

```json
{ "mcpServers": { "devin-memory": { "command": "devin-memory-mcp", "args": ["--db", "/path/to/memory.db"] } } }
```

**Antigravity** — `~/.gemini/config/mcp_config.json`:

```json
{ "mcpServers": { "devin-memory": { "command": "devin-memory-mcp", "args": ["--db", "/path/to/memory.db"] } } }
```

Tools: `retain`, `recall`, `screen` (dry-run the gate, no write), `list`,
`retract`, `supersede`, `quarantine`, `release`, `approve`, `conflicts`,
`prime`, `verify`, `extract`, `compact`, `quarantine_digest`. The `release`
and `approve` promotion overrides are only registered when the server runs
with `DEVIN_MEMORY_MCP_PROMOTE=1` — otherwise promotion stays human-only via
the CLI (`devin-memory quarantine --release <id>` / `devin-memory approve
<id>`). The same flag gates `extract`'s `auto_approve` parameter, which is
forced off without the opt-in so an AI client cannot skip the review step.
Every tool returns structured data or a `{"error", "detail"}`
object — nothing raises through the transport. `DEVIN_MEMORY_DB` works as an
alternative to `--db`.

**VS Code:** `adapters/vscode/` ships an extension that registers this
server with the editor's built-in MCP support (server definition provider,
VS Code ≥1.102) — launch command, optional `DEVIN_MEMORY_DB` and workspace
`cwd` are declared there; the promotion opt-in is pinned off so the
editor-facing server keeps its non-promoting surface.

`adapters/` is a self-contained Devin plugin root
(`adapters/.devin-plugin/plugin.json` + `adapters/skills/devin-brain/SKILL.md`),
installed with
`devin plugins install Icaro0310/devin-brain#adapters` — it ships in the
repo, not inside the wheel. The manifest launches the server through
`uvx --from 'devin-memory[mcp]' devin-memory-mcp`; the promotion
opt-in (`DEVIN_MEMORY_MCP_PROMOTE`) is never set, so the plugin-facing
server keeps its non-promoting surface. To run against a checkout
instead of PyPI, point a local manifest copy at
`uvx --from '.[mcp]' devin-memory-mcp`.

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

Once drafts sit in a skills tree, `catalog-bridge` registers them into the
[devin-skill-catalog](https://github.com/Icaro0310/devin-devkit) registry as
`proposed` entries — closing the write→gate→promote loop:

```bash
# scans .devin/skills/learned-*/SKILL.md and registers each as `proposed`
devin-learning catalog-bridge .devin/skills

# then the catalog gates and promotes them (its own CLI):
devin-skill-catalog quarantine skill:learned-testing . --apply
devin-skill-catalog promote  skill:learned-testing --apply
devin-skill-catalog activate skill:learned-testing --apply
```

The registry defaults to
`<config-dir>/.devin-ecosystem/skill-catalog.json` (resolved like
`devin-skill-catalog`; `DEVIN_CONFIG_DIR` wins) — override with
`--registry`. Entries carry metadata only (`kind`, `name`, `state`,
`sha256` of the SKILL.md, `origin` dir, empty `history`) — draft bodies are
never copied. The bridge is deterministic and idempotent: re-scanning an
unchanged draft changes nothing, an edited draft refreshes `sha256`, and
items the catalog already moved past `proposed` are reported as skipped and
left untouched. `--dry-run` prints the plan without writing. See
[docs/skill-catalog-bridge.md](docs/skill-catalog-bridge.md) for the
contract.

For a shareable summary there is `weekly-report` — the public surface of the
loop. It emits `weekly-YYYY-Www.md` with aggregate counts only (lessons by
theme, promoted `learned-*` skills, quarantine-pending buckets): no session
text, ids or paths, so the file is safe to commit. It resumes from the
`devin-learning-weekly` cursor, falling back to the last `--days` (default 7).

```bash
devin-learning weekly-report --sessions-db path/to/sessions.db --out ./docs/learning
```

## Memory states

`active` · `proposed` (extracted, awaiting `approve`) · `quarantined`
(screened or manually flagged, awaiting `release`) · `retracted` (withdrawn or
superseded). Only `active` entries surface in `recall`/`prime`/`export` —
quarantined content is never printed and never recalled.

An `active` entry can also carry `expires_at` (ISO-8601, set at `retain`/
`supersede` or changed via `set_expires_at`): once the instant passes the
entry is excluded from `recall`/`prime` — excluded, not deleted, so it stays
visible in `list`/`export --all` for audit (`recall --include-expired`
opts out). Entries without `expires_at` never expire. Separately, `recall`
applies an exponential recency decay to keyword scores (half-life 30 days,
`ops.RECALL_DECAY_HALF_LIFE_DAYS`, tunable per call via `half_life_days`) —
fresher memories win close calls while clearly stronger stale hits still
rank first.

## Conflicts, extraction and prime (heuristics)

- **Conflicts** — a `retain` that gives the opposite directive about the same
  normalized subject as an existing active entry is stored alongside it with a
  `conflicts_with` link (`devin-memory conflicts`). The heuristic compares a
  stop-word-stripped "subject key" plus affirmative/prohibitive polarity — it
  deliberately misses reworded contradictions rather than mislinking facts.
- **`extract`** scans one session's `message_nodes` (read-only via
  devin-internals) for durable-knowledge signals — user corrections
  ("na verdade", "actually", "the right way"), preferences ("always", "never",
  "sempre", "nunca"), discovered commands (backticked known tools) and paths.
  Candidates are screened like any write: clean ones land `proposed`,
  suspect ones `quarantined`. `--auto-approve` skips the review step.
- **`prime`** emits a compact `# devin-memory: recalled context (heuristic)`
  block sized for a prompt hook. Entries scoped with `retain --workspace`
  only prime inside that workspace; entries written under a different
  machine profile never prime (the profile defaults to `corporate` —
  fail-closed).
- **`compact`** deduplicates: non-retracted entries sharing exact
  `content` + `workspace` + `profile` collapse to one survivor — the
  liveliest status wins (`active` > `proposed` > `quarantined`), ties keep
  the oldest row. The other copies become `retracted` (never deleted —
  history and reasons stay auditable) and the survivor inherits the union
  of tags from copies sharing its status — quarantined or proposed tags
  never bleed into an active entry. Default is a
  dry-run report (live entries N→M, per-group `keep`/`retracted` ids,
  truncated content sha256 — never content); `--apply` executes and runs
  `VACUUM` on the file.
- **`quarantine --digest`** prints a deterministic audit fingerprint of the
  lane: entry count, reason buckets by taxonomy family (free-form manual
  reasons collapse to `manual:*`), and a sha256 over the sorted per-entry
  fingerprints `sha256(content)+sorted(reasons)`. Keyed on content, not row
  ids — two stores holding the same quarantined facts digest identically,
  and any membership or reason change moves it. Always read-only.

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

- **Extraction is heuristic, and proposed by default.** `extract` lifts
  keyword-shaped sentences from one session into a `proposed` review queue —
  nothing becomes active without `approve` (or `--auto-approve`). For a
  richer lesson pipeline see `devin-learning`.
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
- **PyPI distributions:** `devin-memory` for the CLI and optional MCP extra; `devin-memory-mcp` is the standalone MCP-registry package.

## When to use this

- You persist agent memory between sessions and want it distrust-by-default: every write screened, suspect entries quarantined for human release.
- You need to answer "where did this memory come from?" — entries carry `source_session_id`/`source_rowid`, auditable via `verify`.
- You want memory versioning — `supersede`/`retract` keep a history instead of silent edits.
- You want to stay compatible: `export` writes the Devin memory MCP's `memories.jsonl` line shape.

## When NOT to use this

- You need semantic recall — ranking is keyword-based, no embeddings.
- You expect the screen to catch everything — it is a heuristic filter; run dedicated scanners (gitleaks, devin-redact) alongside.
- You expect `extract` to read intent — it matches keyword signals and defaults to `proposed` precisely because heuristics err.

## FAQ

**How do I stop agent memory from being poisoned by a bad session?** Use `devin-memory retain` instead of appending to a raw store. Every write is screened for secret and injection shapes — suspect entries land in quarantine and only become active after a human runs `quarantine --release <id>`.

**Can devin-memory prove a memory came from a real session?** Yes, via recorded provenance. `retain --source-session <id> --source-rowid <n>` stores the claimed origin, and `devin-memory verify <id> --sessions-db <path>` audits it read-only against Devin's actual `sessions.db` — a fabricated source is checkable, not silently trusted.

**Does devin-memory replace the Devin memory MCP?** It complements it. The MCP is append-only with no screening; devin-memory adds quarantine, provenance and versioning, and `devin-memory export --out memories.jsonl` produces the exact line shape the MCP reads.

## License

MIT — see [LICENSE](LICENSE).
