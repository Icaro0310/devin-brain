"""Auto-extraction (MM-1): durable-knowledge signals in one session.

``devin-memory extract`` scans a single session's ``message_nodes`` —
read-only, through devin-internals' :class:`SessionsStore` — and lifts
sentences that look like durable knowledge into *proposed* memory entries
(not ``active`` until a human ``approve``s them, or ``--auto-approve``).

Signal taxonomy (heuristic, EN + PT — intentionally high-precision):

- ``correction`` — the user steering the agent: *"na verdade"*,
  *"actually"*, *"in fact"*, *"the right way"*, *"o certo"*.
- ``preference`` — standing rules: *"always"*, *"never"*, *"sempre"*,
  *"nunca"*, *"prefira"*, *"instead of"*, *"em vez de"*.
- ``command`` — a discovered invocation: an inline `` `code` `` span whose
  first token is a known CLI tool (git, pytest, pip, docker, …).
- ``path`` — a discovered location: an absolute or ``~/``/``./`` path or a
  Windows ``C:\\`` path mentioned inline.

Roles scanned: ``user``/``human`` **and** ``assistant``/``agent`` —
corrections and preferences are user-shaped, but discovered commands and
paths surface in either. Tool-call payloads are skipped because they do
not decode to the ``text``/``content``/``message`` keys.

Every candidate still goes through :func:`devin_memory.screen.screen`:
secret- or injection-shaped sentences land in ``quarantined``, never in
``proposed``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from devin_internals.parsers.sessions import MessageNode

# --- signal patterns -------------------------------------------------------

CORRECTION_RX = re.compile(
    r"\b(?:na\s+verdade|na\s+real|actually|in\s+fact|the\s+right\s+way"
    r"|o\s+certo|correction|corrigindo|corrija)\b",
    re.IGNORECASE,
)

PREFERENCE_RX = re.compile(
    r"\b(?:always|never|sempre|nunca|jamais|prefer(?:e|o|ir|ia)?"
    r"|prefira|prefiro|em\s+vez\s+de|instead\s+of|rather\s+than"
    r"|don'?t|doesn'?t|do\s+not)\b",
    re.IGNORECASE,
)

_BACKTICK_RX = re.compile(r"`([^`\n]{2,120})`")

_KNOWN_TOOLS = frozenset(
    {
        "git", "gh", "pytest", "python", "python3", "py", "pip", "pip3",
        "pipx", "uv", "npm", "npx", "node", "pnpm", "yarn", "docker",
        "kubectl", "helm", "terraform", "make", "cmake", "cargo", "go",
        "rg", "grep", "find", "curl", "wget", "ssh", "scp", "rsync",
        "cd", "ls", "mkdir", "rm", "cp", "mv", "chmod", "sudo",
        "sqlite3", "psql", "mysql", "redis-cli", "aws", "gcloud", "az",
        "devin-memory", "devin-learning", "devin-redact", "devin-inspect",
    }
)

_PATH_RX = re.compile(
    r"(?<![\w/.-])(?:/(?:home|Users|etc|usr|opt|var|tmp|srv|mnt|data)"
    r"/[^\s\"'<>|)\]]{2,}|~/[^\s\"'<>|)\]]{2,}|\./[^\s\"'<>|)\]]{2,}"
    r"|[A-Za-z]:\\[^\s\"'<>|]{2,})"
)

SIGNAL_PATTERNS = ("correction", "preference", "command", "path")

_ROLES = frozenset({"user", "human", "assistant", "agent"})
_TEXT_KEYS = ("text", "content", "message")
_SENTENCE_SPLIT_RX = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_TOKEN_RX = re.compile(r"[a-z0-9_.-]+")


@dataclass(frozen=True)
class SignalCandidate:
    """One signal-bearing sentence with provenance back to the store."""

    text: str
    signals: tuple[str, ...]
    session_id: str
    row_id: int
    created_at: int
    source: str = "message_nodes"


def _message_payload(chat_message: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(chat_message)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _role_of(payload: dict[str, Any]) -> str:
    role = payload.get("role")
    return role.lower() if isinstance(role, str) else ""


def _text_of(payload: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RX.split(text) if s.strip()]


def _has_command(sentence: str) -> bool:
    """A backtick span whose first token is a known CLI tool."""
    for span in _BACKTICK_RX.findall(sentence):
        tokens = _TOKEN_RX.findall(span.lower())
        if tokens and tokens[0] in _KNOWN_TOOLS:
            return True
    return False


def signals_of(sentence: str) -> tuple[str, ...]:
    """All signal kinds fired by one sentence, in taxonomy order."""
    hits: list[str] = []
    if CORRECTION_RX.search(sentence):
        hits.append("correction")
    if PREFERENCE_RX.search(sentence):
        hits.append("preference")
    if _has_command(sentence):
        hits.append("command")
    if _PATH_RX.search(sentence):
        hits.append("path")
    return tuple(hits)


def signals_from_nodes(nodes: list[MessageNode]) -> list[SignalCandidate]:
    """Signal-bearing sentences from a session's nodes, in store order."""
    out: list[SignalCandidate] = []
    for node in nodes:
        payload = _message_payload(node.chat_message)
        if payload is None or _role_of(payload) not in _ROLES:
            continue
        for sentence in _sentences(_text_of(payload)):
            signals = signals_of(sentence)
            if signals:
                out.append(
                    SignalCandidate(
                        text=sentence,
                        signals=signals,
                        session_id=node.session_id,
                        row_id=node.row_id,
                        created_at=node.created_at,
                    )
                )
    return out
