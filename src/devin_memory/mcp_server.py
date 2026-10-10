"""``devin-memory`` as an MCP server — the anti-poisoning memory layer
exposed to any MCP client (Devin, Claude Desktop, Cursor) over stdio.

Tools (same semantics as the CLI — all logic lives in :mod:`devin_memory.ops`):

- ``retain``      screen + store a memory (quarantine gate applies)
- ``recall``      keyword-ranked recall, active entries only
- ``screen``      dry-run the quarantine gate — no write
- ``list``        list entries by status
- ``retract``     withdraw an entry (kept for history)
- ``supersede``   replace an entry with a corrected version
- ``quarantine``  move an entry to the quarantine lane
- ``release``     human override: quarantined -> active
- ``approve``     promote a proposed extraction to active
- ``conflicts``   contradiction pairs linked at retain time
- ``prime``       compact recalled-context block for a workspace
- ``verify``      audit an entry's provenance against a sessions.db
- ``extract``     mine a session into proposed entries

The DB is ``./memory.db`` by default — ``--db PATH`` or the
``DEVIN_MEMORY_DB`` env var override it, exactly like the CLI.

Errors surface as ``{"error", "detail"}`` — a tool never raises through
the transport.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from devin_memory import ops
from devin_memory.screen import screen as _screen
from devin_memory.store import MemoryStore

DEFAULT_DB = "memory.db"

# Resolved at import from the env; ``main()`` may overwrite via --db so
# an MCP client config can pin the DB path without touching the env.
_DB_PATH = os.environ.get("DEVIN_MEMORY_DB", DEFAULT_DB)


def _store() -> MemoryStore:
    return MemoryStore(_DB_PATH)


def _err(error: Exception) -> dict:
    return {"error": type(error).__name__, "detail": str(error)[:500]}


def _tags(raw) -> list[str]:
    """Accept 'a,b' or ['a','b'] — MCP clients send either."""
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t).strip() for t in (raw or []) if str(t).strip()]


# ---------------------------------------------------------------------------
# Plain ops — unit-testable without the mcp package
# ---------------------------------------------------------------------------

def do_retain(content: str, tags="", workspace: str = "",
              source_session: str = "", source_rowid: int | None = None) -> dict:
    with _store() as store:
        entry = ops.retain(
            store, content, tags=_tags(tags),
            source_session_id=source_session or None,
            source_rowid=source_rowid,
            workspace=workspace or None,
        )
    return entry.to_dict()


def do_recall(query: str = "", limit: int = 5, tags="") -> list[dict]:
    with _store() as store:
        hits = ops.recall(store, query, limit=limit,
                          tags=_tags(tags) or None)
    return [e.to_dict() for e in hits]


def do_screen(content: str, tags="") -> dict:
    """Dry-run the quarantine gate — returns what ``retain`` would do,
    without writing."""
    result = _screen(content, _tags(tags))
    return {"status": result.status, "reasons": list(result.reasons)}


def do_list(status: str = "", limit: int = 20) -> list[dict]:
    with _store() as store:
        entries = ops.list_entries(
            store, status=status or None, limit=limit)
    return [e.to_dict() for e in entries]


def do_retract(entry_id: int) -> dict:
    with _store() as store:
        return ops.retract(store, entry_id).to_dict()


def do_supersede(entry_id: int, content: str, tags="") -> dict:
    with _store() as store:
        return ops.supersede(
            store, entry_id, content, tags=_tags(tags) or None).to_dict()


def do_quarantine(entry_id: int, reason: str = "") -> dict:
    with _store() as store:
        return ops.quarantine_entry(
            store, entry_id, reason=reason or "manual:mcp").to_dict()


def do_release(entry_id: int) -> dict:
    with _store() as store:
        return ops.release(store, entry_id).to_dict()


def do_approve(entry_id: int) -> dict:
    with _store() as store:
        return ops.approve(store, entry_id).to_dict()


def do_conflicts() -> list[dict]:
    with _store() as store:
        pairs = ops.conflicts(store)
    return [{"newer": n.to_dict(), "older": o.to_dict()} for n, o in pairs]


def do_prime(workspace: str = "", max_tokens: int = 0) -> dict:
    with _store() as store:
        text = ops.prime(
            store, workspace=workspace or None,
            max_tokens=max_tokens or ops.PRIME_DEFAULT_MAX_TOKENS,
        )
    return {"text": text}


def do_verify(entry_id: int, sessions_db: str) -> dict:
    with _store() as store:
        return ops.verify_provenance(store, entry_id, sessions_db)


def do_extract(sessions_db: str, session_id: str = "",
               latest: bool = False, auto_approve: bool = False) -> dict:
    with _store() as store:
        return ops.extract_session(
            store, sessions_db,
            session_id=session_id or None,
            latest=latest,
            auto_approve=auto_approve,
        )


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def _make_app(name: str):
    """MCP server app across SDK versions — mcp 2.x renamed FastMCP to
    MCPServer; both expose .tool() and .run()."""
    try:
        from mcp.server.mcpserver import MCPServer
        return MCPServer(name)
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP
        return FastMCP(name)
    except ImportError as e:
        raise ImportError(
            "The MCP server needs the 'mcp' extra: "
            "pip install 'devin-memory[mcp]'"
        ) from e


def _guarded(fn):
    """Tool wrapper: every ops error becomes a structured {error,detail}."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as error:
            return _err(error)
    wrapper.__name__ = fn.__name__
    return wrapper


def build_server(read_only: bool = False):
    """Build the MCP server. With ``read_only`` the review/mutation ops
    (retract, supersede, quarantine, release, approve, extract) are not
    registered — quarantined/proposed memory can only reach ``active``
    through the human CLI, so an agent can never self-release unreviewed
    memory. Plugin installs launch with this flag; the standalone server
    keeps the full surface.
    """
    server = _make_app("devin-memory")

    @server.tool()
    def retain(content: str, tags: str = "", workspace: str = "",
               source_session: str = "",
               source_rowid: int | None = None) -> dict:
        """Screen and store a durable memory. The quarantine gate runs on
        every write — entries flagged secret:/injection:/limit:/shape:
        land in quarantine, never in recall. Returns the stored entry."""
        return _guarded(do_retain)(
            content, tags, workspace, source_session, source_rowid)

    @server.tool()
    def recall(query: str = "", limit: int = 5, tags: str = "") -> list[dict]:
        """Keyword-ranked recall over active memories only — quarantined
        and retracted entries never leak into context."""
        return _guarded(do_recall)(query, limit, tags)

    @server.tool()
    def screen(content: str, tags: str = "") -> dict:
        """Dry-run the anti-poisoning gate: returns the status retain
        would produce (active | quarantined + reasons) without writing."""
        return _guarded(do_screen)(content, tags)

    @server.tool()
    def list(status: str = "", limit: int = 20) -> list[dict]:
        """List memory entries, optionally by status (active, proposed,
        quarantined, retracted)."""
        return _guarded(do_list)(status, limit)

    if not read_only:

        @server.tool()
        def retract(entry_id: int) -> dict:
            """Withdraw an entry — kept for history, never recalled."""
            return _guarded(do_retract)(entry_id)

        @server.tool()
        def supersede(entry_id: int, content: str, tags: str = "") -> dict:
            """Replace an entry with a corrected version (versioned)."""
            return _guarded(do_supersede)(entry_id, content, tags)

        @server.tool()
        def quarantine(entry_id: int, reason: str = "") -> dict:
            """Move an entry to the quarantine lane (review hold)."""
            return _guarded(do_quarantine)(entry_id, reason)

        @server.tool()
        def release(entry_id: int) -> dict:
            """Human override: move a quarantined entry back to active."""
            return _guarded(do_release)(entry_id)

        @server.tool()
        def approve(entry_id: int) -> dict:
            """Promote a proposed extraction to active memory."""
            return _guarded(do_approve)(entry_id)

    @server.tool()
    def conflicts() -> list[dict]:
        """Contradiction pairs linked at retain time (both kept)."""
        return _guarded(do_conflicts)()

    @server.tool()
    def prime(workspace: str = "", max_tokens: int = 0) -> dict:
        """Compact recalled-context block for a workspace — global plus
        workspace-scoped active memories, token-bounded."""
        return _guarded(do_prime)(workspace, max_tokens)

    @server.tool()
    def verify(entry_id: int, sessions_db: str) -> dict:
        """Audit an entry's provenance against a Devin sessions.db
        (read-only)."""
        return _guarded(do_verify)(entry_id, sessions_db)

    if not read_only:

        @server.tool()
        def extract(sessions_db: str, session_id: str = "",
                    latest: bool = False, auto_approve: bool = False
                    ) -> dict:
            """Mine a Devin session (read-only sessions.db) for durable
            knowledge -> proposed entries awaiting approve."""
            return _guarded(do_extract)(
                sessions_db, session_id, latest, auto_approve)

    return server


def main() -> None:
    global _DB_PATH
    parser = argparse.ArgumentParser(
        prog="devin-memory-mcp",
        description="devin-memory MCP server (stdio)",
    )
    parser.add_argument("--db", metavar="PATH",
                        help="memory.db path (default: ./memory.db or "
                             "$DEVIN_MEMORY_DB)")
    parser.add_argument("--read-only", action="store_true",
                        help="expose only the gated read/write surface — "
                             "review ops (approve/retract/supersede/"
                             "quarantine/release/extract) stay CLI-only")
    args = parser.parse_args()
    if args.db:
        _DB_PATH = args.db
    try:
        build_server(read_only=args.read_only).run()
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
