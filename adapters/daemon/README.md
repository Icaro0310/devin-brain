# devin-memory — daemon adapters: intentionally none

**Decision (2026-10-12): no daemon unit ships for this package.** Every
other `adapters/daemon/` dir in the ecosystem wraps a CLI in a scheduler;
here there is nothing correct to wrap.

## Why the MCP server is not a daemon candidate

`devin-memory-mcp` speaks **stdio only** — `mcp_server.py` calls
`build_server().run()` on the stock MCP server transport. It is spawned
per-session by whichever MCP client configured it (Devin, Claude Desktop,
Cursor — `uvx devin-memory-mcp` / `uvx --from devin-memory[mcp]
devin-memory-mcp`), reads requests from stdin, and exits when the client
closes the pipe. There is no socket, port, or listener for a supervisor
to keep alive:

- **A resident copy is unreachable.** systemd could hold a
  `devin-memory-mcp` process open, but no client could ever connect to
  it — the transport is the stdin/stdout pair the spawning client owns.
- **A resident copy is harmful.** The server opens `memory.db`; an
  orphaned instance holding the sqlite file just adds lock contention
  against the instances clients actually spawn.
- **The lifecycle is already correct.** Exit-on-stdin-close is the
  designed behavior; a `Restart=` policy would fight it.
- **The trust model is per-launch.** Promotion tools (`release`,
  `approve`) only register when the operator launches the server with
  `DEVIN_MEMORY_MCP_PROMOTE=1` — a shared always-on server would blur an
  intentionally per-client boundary.

## What about scheduled maintenance?

Everything the package needs periodically is exposed as CLI subcommands
(`devin-memory compact`, `devin-memory extract`, ...), and none of them
are required for correctness — they are hygiene, run by hand when wanted.
If a recurring compact is ever desired, the shape is a **systemd user
timer running the existing CLI** (`Type=oneshot`,
`ExecStart=devin-memory compact --apply`), i.e. the same pattern as the
`devin-switch-drift` units in devin-control — not a new service around
the MCP server. Ship it only when a real cadence exists; none does
today.

> **Status:** this decision is new (recorded 2026-10-12) — revisited if a
> network transport is ever added to the MCP server. Until then, absence
> of a unit here is deliberate, not a gap.

> Unofficial community project. Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.
