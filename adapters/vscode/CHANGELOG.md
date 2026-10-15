# Changelog

## [0.1.1]

### Fixed

- First published build carrying the Restricted Mode support — the
  0.1.0 package uploaded to Open VSX predated it.

## [0.1.0]

### Security

- Declared `capabilities.untrustedWorkspaces` (`supported: "limited"`)
  with `restrictedConfigurations` covering `devinMemory.executable`,
  `devinMemory.args` and `devinMemory.dbPath`; in Restricted Mode the
  MCP server's `cwd` is anchored to extension storage instead of the
  workspace, so an untrusted repository can no longer supply the default
  `./memory.db` returned by MCP recall.
- `safe-executable` hardening: PATH candidates are `realpath`'d before
  the inside-workspace check (a PATH entry symlinked into the repo no
  longer evades it), every workspace root is rejected in Restricted
  Mode rather than only the first (multi-root), and `%dp0%`-style npm
  shims resolve alongside `%~dp0`. The restricted-mode storage
  directory is created on first launch so a fresh install's missing
  global storage can no longer break the spawn.

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
