"""Contradiction heuristics (MM-2): same topic, opposite directive.

The detector is intentionally simple and deterministic — it answers one
question: *do these two texts give the opposite instruction about the same
subject?*

- ``subject_key(text)`` — the set of significant tokens once directive and
  stop words are removed. Two memories "about the same thing" share a key:
  ``"always run pytest before pushing"`` and ``"never run pytest before
  pushing"`` both reduce to ``{pytest, pushing}``.
- ``polarity(text)`` — ``"pos"`` when the text carries an affirmative
  directive marker (always / use / prefer / deve…), ``"neg"`` for a
  prohibitive one (never / don't / avoid / nunca…), ``"neutral"`` when
  neither fires. Negative wins when both match — ``"never use X"`` is a
  prohibition that happens to contain ``use``.

``is_conflict(a, b)`` fires only when the subject keys are identical, the
normalized contents differ, and the polarities are opposite. Identical
content is a duplicate, not a conflict; same-key same-polarity entries are
consistent restatements, not contradictions.

Known limits (documented, accepted): reworded contradictions
(``"use black"`` vs ``"use ruff"``) have different keys and pass silently —
recall is keyword-based, and so is this detector. False negatives are
preferable to linking unrelated entries.
"""

from __future__ import annotations

import re

_TOKEN_RX = re.compile(r"[a-z0-9_]+")

# Directive words carry polarity, not topic — removed from subject keys.
_POLARITY_WORDS = frozenset(
    {
        "always", "never", "sempre", "nunca", "jamais",
        "use", "using", "usa", "usar", "prefer", "prefira", "prefiro",
        "avoid", "evite", "evitar",
        "don", "do", "does", "not", "no", "não", "nao",
        "must", "should", "deve", "deveria", "precisa",
        "enable", "disable", "run", "rode", "execute", "executar",
        "instead", "vez", "rather", "than",
    }
)

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "o", "os", "as", "um", "uma",
        "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
        "para", "pra", "com", "por", "sem", "sobre",
        "in", "on", "at", "to", "for", "with", "without", "of", "from",
        "and", "or", "e", "ou", "is", "are", "was", "were", "be",
        "this", "that", "it", "its", "we", "you", "i", "my", "your", "our",
        "meu", "sua", "seu", "este", "esta", "isso", "esse", "essa",
        "before", "after", "antes", "depois", "when", "quando",
        "please", "favor", "make", "faz", "faça", "way", "jeito",
        "right", "certo", "correct", "correto",
    }
)

_POSITIVE_RX = re.compile(
    r"\b(?:always|sempre|use|usa|usar|prefer|prefira|prefiro|must|should"
    r"|deve|deveria|enable|instead\s+of|em\s+vez\s+de|rather\s+than)\b",
    re.IGNORECASE,
)
_NEGATIVE_RX = re.compile(
    r"\b(?:never|nunca|jamais|avoid|evite|evitar|don'?t|doesn'?t|do\s+not"
    r"|não|nao|disable|stop|no\s+longer|sem)\b",
    re.IGNORECASE,
)


def subject_key(text: str) -> frozenset[str]:
    """Significant-topic tokens of ``text`` (directive + stop words removed)."""
    return frozenset(
        t
        for t in _TOKEN_RX.findall(text.lower())
        if len(t) > 1 and t not in _POLARITY_WORDS and t not in _STOPWORDS
    )


def polarity(text: str) -> str:
    """``"neg"`` | ``"pos"`` | ``"neutral"`` — negative wins on ties."""
    if _NEGATIVE_RX.search(text):
        return "neg"
    if _POSITIVE_RX.search(text):
        return "pos"
    return "neutral"


def _norm(text: str) -> str:
    return " ".join(_TOKEN_RX.findall(text.lower()))


def is_conflict(new_text: str, old_text: str) -> bool:
    """True when two texts give opposite directives about the same subject."""
    key = subject_key(new_text)
    if not key or key != subject_key(old_text):
        return False
    if _norm(new_text) == _norm(old_text):
        return False  # same statement, not a contradiction
    return {polarity(new_text), polarity(old_text)} == {"pos", "neg"}
