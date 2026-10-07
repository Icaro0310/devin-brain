# Changelog

## Unreleased (F4)

- **CI** — `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.

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

## 0.2.0

- Absorbed the `devin-learning` project: extract/report/review/skills now
  live in `devin_memory.learning`. The `devin-learning` console script
  remains as a compatibility alias. Added `devin-redact` dependency
  (learning pipeline imports it).
- Merged all learning tests (108 total). The `devin-learning` repo is
  archived/deleted — this package is the canonical home.

## 0.1.0

- Initial release: anti-poisoning memory layer for Devin.
