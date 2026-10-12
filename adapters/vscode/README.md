# devin-memory for VS Code

Registers the [devin-memory](https://github.com/Icaro0310/devin-brain) MCP
server — anti-poisoning memory for agents, with provenance, conflicts and a
quarantine gate — with VS Code's built-in MCP support.

Thin adapter: the extension uses the MCP server definition provider API to
declare *how to launch* the server. Every tool the server exposes and every
check it runs lives in `devin-memory-mcp` itself — nothing is reimplemented
here.

## Requirements

- VS Code ≥ 1.102 (stable `vscode.lm.registerMcpServerDefinitionProvider` API).
- `devin-memory-mcp` on `PATH` (`pipx install devin-memory-mcp`), or point
  `devinMemory.executable`/`devinMemory.args` at another launcher
  (e.g. `uvx` + `devin-memory-mcp`).

Compatible server range: `>=0.3.1,<0.4.0` (pinned as `devin-memory-mcp` in
`package.json`; `test/cli-contract.test.js` keeps the pin, the
`COMPATIBLE_CLI` bounds and `packaging/devin-memory-mcp/pyproject.toml`
in sync).

## How it works

The extension contributes one MCP server definition provider
(`devin-memory`). When VS Code collects MCP servers — MCP: List Servers,
Copilot agent tools, etc. — it activates this extension, which returns a
stdio definition:

- **command**: `devinMemory.executable` (default `devin-memory-mcp`)
- **args**: `devinMemory.args` (default `[]`)
- **env**: built from scratch — `DEVIN_MEMORY_DB` only when
  `devinMemory.dbPath` is set
- **cwd**: the first workspace folder's `Uri` (assigned on the definition,
  so the server's default `./memory.db` lands in the project)

**Safety**: `DEVIN_MEMORY_MCP_PROMOTE` is pinned to `"0"` — even if the
editor's ambient environment carries the opt-in, the server never sees it.
The `release`/`approve` promotion overrides stay human-only, and every
write still passes through the quarantine gate.

When `devinMemory` settings or workspace folders change, the provider
fires `onDidChangeMcpServerDefinitions` so VS Code re-collects the
definition instead of launching a stale one.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `devinMemory.executable` | `devin-memory-mcp` | Server executable |
| `devinMemory.args` | `[]` | Executable arguments |
| `devinMemory.dbPath` | `""` | `DEVIN_MEMORY_DB` (empty = `./memory.db` under the workspace folder) |

## Development

```sh
npm test        # node --test (provider/definition tests + pin contract)
```
