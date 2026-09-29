# SPEC — `devin-memory` (M1)

## 1. Problem

Agent memory is a poisoning vector. Any long-running agent that persists
"facts" between sessions can be silently corrupted by a single bad session:
a hostile or confused run writes something wrong (or malicious — an injected
instruction, a harvested secret), and every *future* session trusts it. There
is no review step, no provenance, no way to say "where did this belief come
from?".

Existing memory layers (the Devin memory MCP's `retain`/`recall`, MemGPT-style
stores, LangChain memory) are append-only key-value bags: they optimize for
*remembering*, not for *being able to distrust what was remembered*.

## 2. Devin extra (and the 3 tests)

**Extra:** every memory carries **provenance back to session rows** —
`source_session_id` + `source_rowid` auditable against Devin's `sessions.db`
through `devin-internals`' read-only `SessionsStore`. Plus a **quarantine
gate** (vendored devin-redact-style secret regexes + injection heuristics +
size/shape limits) so suspect content never reaches `active` without a human.

- **Side-by-side:** the memory MCP `retain` writes whatever it is given, with
  no screening and no link back to where the fact was observed. `devin-memory`
  quarantines secret-shaped and injection-shaped content and can verify a
  claimed source against the real session store — the base tool cannot do
  either.
- **No-Devin:** without Devin's `sessions.db` there is no session provenance
  to audit — the extra disappears.
- **One sentence:** *"It's a memory store that remembers where each memory
  came from — and refuses to trust suspicious ones until a human says so."*

## 3. Scope (M1)

`src/devin_memory/`:

- `store.py` — own SQLite `memory.db` (the only writable store in the
  ecosystem; Devin's stores are never touched for writing). Table
  `entries(id, content, tags[], source_session_id, source_rowid, created_at,
  status, version, supersedes_id, quarantine_reasons[])`;
  `status ∈ {active, quarantined, retracted}`.
- `screen.py` — quarantine gate: secret regexes (vendored from
  devin-redact; **no hard dep** in M1), injection heuristics, size/shape
  limits → `ScreenResult(status, reasons)`; reasons persist on the row.
- `ops.py` — `retain` / `recall` / `retract` / `supersede` / `release` /
  `list_entries` / `verify_provenance`. `recall` returns `active` only.
- `export.py` — dump to `memories.jsonl` in the memory-MCP line shape.
- `cli.py` — thin wrapper (`devin-memory`).

## 4. Non-scope

- **No auto-extraction** — M1 is a primitive: it stores what it is told via
  `retain`. Deriving memories from sessions is M2 (`devin-learning` pipeline).
- No MCP server wrapper yet (M2).
- No conflict detection, embeddings, or semantic dedup — `recall` ranking is
  deterministic keyword scoring on purpose.
- No hard dependency on `devin-redact` (regexes vendored; swap to the real
  package later).
- Never writes to Devin's stores (`sessions.db`, `acp-messages`,
  `state.vscdb` stay read-only via devin-internals).

## 5. Interfaces

| Interface | Description |
|---|---|
| Library `devin_memory` | store / screen / ops / export |
| CLI `devin-memory` | `retain` · `recall` · `quarantine` · `retract` · `supersede` · `list` · `export` · `verify` |
| DB | `./memory.db` (override: `--db` flag or `DEVIN_MEMORY_DB`) |

## 6. Output format / data contract

- `recall`/`list`/`quarantine --json` emit `Entry` dicts:
  `{id, content, tags[], source_session_id, source_rowid, created_at (ms),
  status, version, supersedes_id, quarantine_reasons[]}`.
- `verify` emits `{entry_id, sessions_db, source_session_id, source_rowid,
  checked, session_found, rowid_found}`; exit 0 iff provenance checks out.
- `export` emits one JSON object per line, memory-MCP-compatible:
  `{id (12-hex, stable), ts, iso, content, tags, source: "session:<id>" |
  "devin-memory"}` plus optional `source_rowid`, `version`, `supersedes`
  (export id of the predecessor). Only `active` entries unless `--all`.

## 7. Semantics worth pinning down

- `retain` always screens first; `status` on insert is the gate's verdict.
- `release` (`quarantine --release`) is an explicit human override —
  quarantined→active; the reasons stay on the row for audit.
- `supersede` atomically retracts the old row and inserts the successor with
  `version+1`/`supersedes_id`; the replacement is screened like any retain
  (if it quarantines, the old version is still retired — review the queue).
- `retracted` covers both user-retracted and superseded rows; the
  `supersedes_id` link on the newer row distinguishes them.

## 8. Fixtures and tests (TDD — fixtures first)

`tests/fixtures.py` builds synthetic content: clean facts, **fake** secrets
(assembled by concatenation so the repo's own redact-check CI never sees a
literal secret shape), injection phrasings, oversize/base64 shapes, and a
fixture `sessions.db` via `devin_internals.fixtures` for provenance tests.
71 tests: schema, screening verdicts per family, recall ranking,
active-only recall, supersede history, export shape/stability, CLI wiring.

## 9. Risks and mitigation

| Risk | Mitigation |
|---|---|
| False positives quarantine legit facts | Release path is one command; reasons are stored and shown |
| Screening is a filter, not a guarantee | Documented; complements gitleaks/devin-redact, never replaces |
| Provenance claims can themselves be fake | `verify` audits against the real store; write-time verification flag is M2 material |
| Schema drift in `sessions.db` | Gated by devin-internals' version detector — unknown versions fail loudly |

## 10. Definition of done

- [x] `python -m pytest` green (71 tests)
- [x] `devin-memory` CLI verified end-to-end (retain→quarantine→release,
  supersede chain, export, verify exit codes)
- [x] `docs/SPEC.md`, README EN/PT-BR, STATUS.md, CHANGELOG.md
- [x] Explicit limitation: M1 is a primitive — no auto-extraction yet
- [ ] PyPI publish (`pipx install devin-memory`)

## 11. M2 queue

1. `devin-learning` pipeline in (auto-extraction → quarantine queue).
2. MCP server wrapper (`retain`/`recall`/`reflect` over this store).
3. Conflict detection (contradicting active entries).
4. PyPI publish.
