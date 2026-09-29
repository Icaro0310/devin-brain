# STATUS — devin-memory

Updated: 2026-09-29 · Milestone: **M1 (done)** · Version: 0.1.0

## Done in M1

- `src/devin_memory/store.py` — `memory.db`, the only writable store in the
  ecosystem: `entries(id, content, tags[], source_session_id, source_rowid,
  created_at, status, version, supersedes_id, quarantine_reasons[])` with
  `status ∈ {active, quarantined, retracted}`. Frozen `Entry` dataclass,
  idempotent schema, newest-first ordering.
- `src/devin_memory/screen.py` — quarantine gate: vendored
  devin-redact-style secret regexes (no hard dep), injection heuristics
  (ignore/disregard/forget instructions, ChatML+`<<SYS>>` markers,
  reveal/override prompt phrasing, unrestricted-`act as`, jailbreak terms),
  size/shape limits (32 KiB content, 32 tags, tag charset, NUL, long
  base64 runs). Reasons persist on the row for audit.
- `src/devin_memory/ops.py` — `retain` (screens on write), `recall`
  (active-only, deterministic keyword ranking), `retract`, `release`
  (human override, reasons kept), `supersede` (atomic retract+insert,
  version chain), `list_entries`, `verify_provenance` (audits
  session_id+rowid against `sessions.db` via devin-internals read-only
  `SessionsStore`).
- `src/devin_memory/export.py` — `memories.jsonl` in the memory-MCP line
  shape (`{id, ts, iso, content, tags, source}`); stable 12-hex ids;
  optional `source_rowid`/`version`/`supersedes` extras; active-only by
  default, `--all` to include quarantined/retracted.
- `src/devin_memory/cli.py` — thin `devin-memory` wrapper:
  `retain` · `recall` · `quarantine [--list|--release]` · `retract` ·
  `supersede` · `list` · `export` · `verify`. Global `--db` /
  `DEVIN_MEMORY_DB` (default `./memory.db`).
- Dependency: `devin-internals-spec @ git+…@v0.2.0` declared in
  pyproject; installed locally as editable sibling.
- Tests: **71 green** (Windows, Python 3.11.9, pytest 9.1.1) —
  fixtures-first; fake secrets concatenated so redact-check CI never sees
  a literal secret shape.
- Docs: `docs/SPEC.md`, README EN/PT-BR (real content incl. the explicit
  "M1 is a primitive — no auto-extraction yet" limitation).

## Environment notes

- `python` = 3.11.9 w/ pytest 9.1.1; bare `pip` → Python 3.14. Always
  `python -m pip`.
- exec runs under **cmd.exe**: no heredocs, no multi-line `python -c`;
  commit messages need repeated `-m` flags.
- Install editable without touching the git dep:
  `python -m pip install -e ".[dev]" --no-deps` (dep already in env).

## Decisions / notes

- `retracted` covers user-retracted *and* superseded rows (spec lists
  exactly 3 statuses); the successor's `supersedes_id` distinguishes them.
- Superseding with quarantined content still retires the old version —
  the replacement waits in the queue; documented in SPEC §7/README.
- Release keeps `quarantine_reasons` on the row — release is an audit
  event, not an erasure.
- Export ids are derived from `(rowid, created_at)` — stable across
  re-exports, content-independent.

## M2 queue (per kickoff)

1. `devin-learning` pipeline in (auto-extraction → quarantine queue).
2. MCP server wrapper (`retain`/`recall`/`reflect` over this store).
3. Conflict detection (contradicting active entries).
4. PyPI publish (`pipx install devin-memory`).
5. Optional: `retain --verify` write-time provenance check against a
   `sessions.db` flag; FTS5 recall; screening via the real `devin-redact`
   package instead of vendored regexes.

## Blockers

None.
