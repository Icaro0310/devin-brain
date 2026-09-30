"""Extract lesson candidates from user messages in a ``sessions.db``.

Read-only: goes through :class:`devin_internals.parsers.sessions.SessionsStore`,
which gates on the schema detector before opening the database in ``mode=ro``.
A *candidate* is a single sentence (or line) of user text matching the lesson
regex seed set — extraction is intentionally greedy; :mod:`.review` decides
what is safe to promote.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devin_internals.parsers.sessions import SessionsStore

# Regex seed set (EN + PT) — kickoff M1.
LESSON_RX = re.compile(
    r"\b(?:sempre|always|nunca|never|prefira|prefer|em vez de|instead of"
    r"|lembra|remember|don't|do not)\b",
    re.IGNORECASE,
)

_USER_ROLES = frozenset({"user", "human"})
_TEXT_KEYS = ("text", "content", "message")
_SENTENCE_SPLIT_RX = re.compile(r"(?<=[.!?])\s+|[\r\n]+")


@dataclass(frozen=True)
class Candidate:
    """One lesson-shaped sentence with provenance back to the store."""

    text: str
    session_id: str
    node_id: int
    created_at: int
    source: str = "message_nodes"


def _message_payload(chat_message: str) -> dict[str, Any] | None:
    """Decode ``chat_message`` JSON; returns ``None`` if it is not an object."""
    try:
        obj = json.loads(chat_message)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _role_of(payload: dict[str, Any]) -> str:
    role = payload.get("role")
    if isinstance(role, str):
        return role.lower()
    return ""


def _text_of(payload: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RX.split(text) if s.strip()]


def extract_candidates(db_path: str | Path) -> list[Candidate]:
    """All lesson-shaped sentences from user messages, in store order.

    Raises:
        SchemaError: database missing, not a sessions.db, or an unknown /
        unsupported schema version (propagated from devin-internals-spec).
    """
    candidates: list[Candidate] = []
    with SessionsStore(db_path) as store:
        for node in store.message_nodes():
            payload = _message_payload(node.chat_message)
            if payload is None or _role_of(payload) not in _USER_ROLES:
                continue
            for sentence in _sentences(_text_of(payload)):
                if LESSON_RX.search(sentence):
                    candidates.append(
                        Candidate(
                            text=sentence,
                            session_id=node.session_id,
                            node_id=node.node_id,
                            created_at=node.created_at,
                        )
                    )
    return candidates
