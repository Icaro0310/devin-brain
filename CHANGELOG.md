# Changelog

## 0.3.1

- `__version__` now matches the published artifact: the 0.3.0 wheel on PyPI self-reports 0.1.0 (built before the version sync landed). This release exists so the index carries a wheel whose metadata and self-report agree.

## Unreleased (F4)

- **CI** — the test job installs `pyyaml` (imported by
  `tests/test_release_workflow.py` but never declared in the install
  step) and enables `core.longpaths` on Windows runners, where pip's
  git clone of `devin-internals-spec` previously failed checkout on
  MAX_PATH and the sibling dependency never installed.

- **Docs** — the missing-`mcp`-extra recovery moved from the shared
  README to the platform guides' Troubleshooting sections, and now
  notes that adding the extra to an existing tool needs `--force`
  (`uv tool install --force 'devin-memory[mcp]'`).

- **`devin-learning weekly-report`** — new public surface of the learning
  loop: writes `weekly-YYYY-Www.md`, an aggregate-only summary (window
  dates, lesson counts by theme, promoted `learned-*` skill names,
  quarantine-pending reason buckets). Unlike `REPORT.md` it carries no
  session text, no session/node identifiers and no filesystem paths, so
  it is safe to commit and share. Incremental via the shared
  `devin-learning-weekly` cursor (`.devin/devin-learning-weekly-state.json`,
  `DEVIN_CURSOR_DIR` override): since the last report, else the last
  `--days` (default 7); `--since` overrides both. The report write is
  atomic (tmp+replace) and the cursor commits only after it lands.
- **`compact`** — new housekeeping subcommand: deduplicates non-retracted
  entries sharing exact `content`+`workspace` to one survivor (liveliest
  status wins, ties keep the oldest row), retracting the other copies —
  rows are never deleted, so provenance stays auditable. Dry-run by
  default (`--apply` executes and `VACUUM`s the file); the report shows
  live N→M, per-group keep/retract ids and truncated content sha256 —
  never content. Also exposed as the `compact` MCP tool.
- **`quarantine --digest`** — read-only audit fingerprint of the
  quarantine lane: count, reason buckets by taxonomy family (manual
  reasons aggregate to `manual:*`), and sha256 over sorted per-entry
  fingerprints `sha256(content)+sorted(reasons)`. Content-keyed, so the
  same quarantined set digests identically across machines; any
  membership/reason change moves it. Also exposed as the
  `quarantine_digest` MCP tool.

- **MCP promotion gate** — the `release` and `approve` tools are no
  longer registered by default: they only appear when the server is
  launched with `DEVIN_MEMORY_MCP_PROMOTE=1`, so an AI-driven MCP client
  cannot self-promote quarantined or proposed content past the review
  lane. `extract`'s `auto_approve` parameter is also forced off without
  the opt-in. Promotion stays human-only via `devin-memory quarantine
  --release <id>` and `devin-memory approve <id>`.

- **VS Code adapter** (`adapters/vscode/`) — registers `devin-memory`
  with the editor's MCP support via the server definition provider API
  (VS Code ≥1.102). Server env is built from scratch with the promotion
  flag pinned off, `cwd` is anchored to the workspace folder so the
  default `./memory.db` lands in the project, and definition changes
  (settings/workspace folders) re-collect via
  `onDidChangeMcpServerDefinitions`. Pins `devin-memory-mcp
  >=0.3.1,<0.4.0`; contract tests keep pin, bounds and packaged version
  in sync at patch level.
- **Docs** — corporate-windows guide: Zscaler root export now requires PEM ("Base-64 encoded X.509" wizard option or `certutil -encode` after `Export-Certificate`, which emits DER) and distinguishes `certmgr.msc` (Current User store) from `certlm.msc` (Local Machine store); the offline recipe installs `setuptools`+`wheel` before `--no-build-isolation`.
- **Docs** — platform guides regenerated (Zscaler section, per-package local-runtime bullet, scheduled extract with explicit `--db`/`--sessions-db`); `mcp-name` kept as `io.github.Icaro0310/devin-memory` to match the published MCP registry identity.
- **Docs** — scheduled job now uses a `.cmd` wrapper under `%USERPROFILE%\devin-tasks` registered via `Register-ScheduledTask`, quoting-safe in cmd.exe and PowerShell and not writable by other local users. The wrapper prepends `%USERPROFILE%\.local\bin` to `PATH`, registration uses `-Force`, and the logon trigger is pinned with `-User $env:USERNAME`.
- **Devin plugin adapter** (`adapters/`) — self-contained Devin plugin
  root: `.devin-plugin/plugin.json` launches `devin-memory-mcp` via
  `uvx --from 'devin-memory[mcp]'` (promotion opt-in stays off) and
  `skills/devin-brain/SKILL.md` teaches the agent the memory surface —
  `retain`/`recall`/`screen`/`list`/`conflicts`/`prime`/`verify` —
  while `release`/`approve` promotion stays human-only via the CLI.
  Ships in the repo, not the wheel: `devin plugins install
  Icaro0310/devin-brain#adapters`. Contract tests pin the manifest,
  the skill frontmatter and the no-promotion-ops surface.
- **Docs** — refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- **Docs** — ecosystem journey recuration recorded (six curated audiences); v2 zero-repeats keeps only this product's AI engineers path — Data Scientists moved to the devin-graph → devin-search → devin-history → devin-metrics chain.
- **Docs** — README gains the generated `Part of the DEVIN ecosystem` block
  (track/nature/audience/interface rendered from the registry).

- **CI** — `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.
- **CI** — the inline `secrets-scan` job now calls the shared reusable, which replaces the blanket `fixtures` exclusion with hash-pinned `.secrets-scan-allow` entries.

- **Install** — README now recommends `uv tool install 'devin-memory[mcp]'` (PyPI) as the primary route; `pipx` documented as alternative.

- **MCP server** — `devin_memory.mcp_server` exposes the same ops over
  stdio as a real MCP server (`devin-memory-mcp` console script,
  `mcp>=1.9` optional extra, SDK 1.x/2.x compatible). Tools: `retain`,
  `recall`, `screen` (dry-run), `list`, `retract`, `supersede`,
  `quarantine`, `release`, `approve`, `conflicts`, `prime`, `verify`,
  `extract`. `server.json` added for the Official MCP Registry;
  `<!-- mcp-name: io.github.icaro0310/devin-memory -->` ownership marker
  in the READMEs.

- **MM-3** — `quarantine <id> [--reason r]` marks an existing entry
  (active or proposed → quarantined; reasons appended for audit).
  `screen.py` now vendors devin-redact's `devin_pairing_code` pattern too.
- **MM-2** — contradiction links: a `retain` giving the opposite directive
  about the same normalized subject as an active entry is stored alongside
  it with `conflicts_with` (new column; `devin_memory.conflict` heuristic).
  New `conflicts` subcommand lists the pairs. `retain` also accepts
  `--workspace` (new column for prime scoping). Migrations stay additive;
  the widened `status` CHECK uses the canonical data-preserving rebuild.
- **MM-1** — `extract <session-id|--latest> --sessions-db DB` mines a
  session's `message_nodes` (read-only) for durable-knowledge signals
  (corrections, preferences, commands, paths — EN+PT heuristic) into
  `proposed` entries; `approve <id>` promotes them, `--auto-approve`
  skips review. Extraction reports never print content.
- **MM-4** — `prime [--workspace PATH] [--max-tokens N]` prints a
  hook-ready recalled-context block: active entries only, filtered by
  workspace + machine profile (corporate default, fail-closed), bounded
  by a ~4 chars/token estimate.
- New `proposed` status: `active` · `proposed` · `quarantined` ·
  `retracted`. Only `active` surfaces in recall/prime/export.
- `llms.txt` no longer states a hard-coded ecosystem size; the registry owns the count.

- **Docs** — platform guides and the README install commands no longer pin a release; they install the latest published version.
- **Fix** — `devin_memory.learning.__version__` is now the submodule's own version (synced with the package release) instead of the root `devin_memory.__version__`; it drives `devin-learning --version` and the `version` field in extract/review reports. Corrects the 0.3.0 note that attributed those outputs to the root module.

## 0.3.0

- **Fix** — `devin_memory.__version__` now reports the package version (was stale at `0.1.0` while `pyproject.toml` declared `0.3.0`); drives `devin-learning --version` and report metadata.
- **CI** — the PyPI publish workflow now verifies the built wheel's self-reported `__version__` against `pyproject.toml` before upload (installed with `--no-deps`, so workspace siblings not yet on PyPI cannot block a valid wheel).

## 0.2.0

- Absorbed the `devin-learning` project: extract/report/review/skills now
  live in `devin_memory.learning`. The `devin-learning` console script
  remains as a compatibility alias. Added `devin-redact` dependency
  (learning pipeline imports it).
- Merged all learning tests (108 total). The `devin-learning` repo is
  archived/deleted — this package is the canonical home.

## 0.1.0

- Initial release: anti-poisoning memory layer for Devin.
