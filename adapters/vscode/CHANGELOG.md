# Changelog

## [0.1.0]

### Added

- MCP server definition provider (`devin-memory`) registering the
  `devin-memory-mcp` stdio server with VS Code's MCP support (≥1.102).
- Launch wiring: configurable `devinMemory.executable`/`args`,
  `DEVIN_MEMORY_DB` only when `devinMemory.dbPath` is set, and `cwd`
  anchored to the first workspace folder so the default `./memory.db`
  lands in the project.
- Env built from scratch with `DEVIN_MEMORY_MCP_PROMOTE` pinned to `0` —
  the promotion overrides (`release`/`approve`) stay human-only even if
  the editor's ambient environment carries the opt-in.
- `onDidChangeMcpServerDefinitions` fires on `devinMemory` setting
  changes and workspace-folder changes so the definition never goes
  stale.
- `devin-memory-mcp` pin (`>=0.3.1,<0.4.0`) in package.json; contract
  tests keep pin, `COMPATIBLE_CLI` and the packaged version in sync.
- Settings: `devinMemory.executable`, `devinMemory.args`,
  `devinMemory.dbPath`.
