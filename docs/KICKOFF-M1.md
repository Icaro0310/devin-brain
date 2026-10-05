# KICKOFF M1 — devin-memory

Dedicated session for THIS repo — this is a RESEARCH wave project; be
conservative, document uncertainty, prefer primitives over magic.
`docs/SPEC.md` EN, a shared README plus Windows/Linux platform guides, logic in `src/devin_memory/` + thin
`cli.py`, small commits + Devin trailer, push, STATUS.md + CHANGELOG.md.

## One sentence

An anti-poisoning memory store: durable facts/learnings with provenance
(which session, when, evidence), versioning, and a quarantine gate — so
agent memory can't be silently corrupted by a bad session or injected
content.

## Devin-native differentiator

Memory entries carry **provenance back to session rows** (session_id +
message rowid via devin-internals) — every fact is auditable to its
source; quarantine uses devin-redact-style secret/injection screening
(vendor regexes — no hard dep on devin-redact in M1).

Dep: `"devin-internals-spec @ git+https://github.com/Icaro0310/devin-internals-spec.git@v0.2.0"`

## Scope (M1)

`src/devin_memory/`:
- `store.py` — `memory.db` (own SQLite, not Devin's): entries(id, content,
  tags[], source_session_id, source_rowid, created_at, status:
  active|quarantined|retracted, version, supersedes_id).
- `screen.py` — quarantine gate: secrets regexes + injection heuristics
  + size/shape limits → status set on insert.
- `ops.py` — retain/recall(keyword)/retract/supersede/list; recall only
  returns `active`.
- `export.py` — dump to `memories.jsonl` (memory-MCP-compatible shape).

## CLI

- `devin-memory retain "<content>" --tags a,b --source-session <id>`
- `devin-memory recall "<query>" [--json]`
- `devin-memory quarantine [--list] [--release <id>]`
- `devin-memory export --out memories.jsonl`
- Owns its DB (only store in the ecosystem that writes) — still never
  touches Devin's stores.

## Fixtures/tests

Unit store + screening: secret content → quarantined; injection shape →
quarantined; recall ranking; supersede keeps history; export format.
Small synthetic content — NO real secrets.

## Env notes

`python`=3.11.9; `python -m pip` only; no multi-line `python -c`; Windows.

## Done

Tests green · CLI verified · docs real incl. explicit "M1 is a
primitive — no auto-extraction yet" limitation · pushed. M2 queue in
STATUS.md: devin-learning pipeline in, MCP server wrapper, conflict
detection, PyPI.
