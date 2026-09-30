"""Anti-poisoning safety gate for lesson candidates.

Two layers, both applied to the candidate text that would be promoted into a
``SKILL.md``:

1. **Secrets** — the candidate is scanned with devin-redact's pattern engine;
   any hit in a secret-class category (API keys, tokens, private keys, env
   assignments, pairing codes) drops it.
2. **Injection heuristics** — shapes that indicate the "lesson" is really an
   attempt to plant instructions or smuggle payloads: instruction-override
   phrases ("ignore previous instructions"), system-prompt exfiltration,
   embedded tool-call JSON blobs, and long base64 runs.

Fail closed: any reason drops the candidate. PII-shaped findings (emails,
absolute paths) do not drop by themselves — they are recorded as warnings so
the report can surface them for human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devin_redact.engine import scan_text
from devin_redact.patterns import SECRET_CATEGORIES

from .extract import Candidate

_INJECTION_RXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b"
            r"(?:previous|prior|above|earlier|preceding)\b[^.\n]{0,40}\b"
            r"(?:instructions?|prompts?|rules?|directions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfil",
        re.compile(
            r"\b(?:reveal|print|show|output|leak|repeat|dump|exfiltrate)\b"
            r"[^.\n]{0,40}\bsystem\s+prompt\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override",
        re.compile(
            r"\b(?:you\s+are\s+now|new\s+instructions|enter\s+\w+\s+mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_call_blob",
        re.compile(
            r"\{[^{}]*\"(?:tool_call_id|toolCallId|function_call|tool_calls"
            r"|arguments)\"\s*:",
        ),
    ),
    (
        "base64_blob",
        re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=])"),
    ),
)


@dataclass(frozen=True)
class Verdict:
    """The safety gate's decision for one candidate."""

    candidate: Candidate
    accepted: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _secret_reasons(text: str) -> tuple[list[str], list[str]]:
    """Run devin-redact's pattern engine on the candidate text."""
    reasons: list[str] = []
    warnings: list[str] = []
    findings = scan_text(text, file="candidate", location="lesson")
    for finding in findings:
        tag = f"{finding['category']}:{finding['pattern']}"
        if finding["category"] in SECRET_CATEGORIES:
            reasons.append(f"secret:{tag}")
        else:
            warnings.append(f"pii:{tag}")
    return sorted(set(reasons)), sorted(set(warnings))


def _injection_reasons(text: str) -> list[str]:
    return [f"injection:{name}" for name, rx in _INJECTION_RXES if rx.search(text)]


def review_text(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Safety gate for arbitrary text: returns ``(reasons, warnings)``.

    Any non-empty ``reasons`` means the text must not be promoted. Shared by
    candidate review and the ``review`` CLI command (draft re-review).
    """
    reasons, warnings = _secret_reasons(text)
    return tuple(reasons + _injection_reasons(text)), tuple(warnings)


def review_candidate(candidate: Candidate) -> Verdict:
    reasons, warnings = review_text(candidate.text)
    return Verdict(
        candidate=candidate,
        accepted=not reasons,
        reasons=reasons,
        warnings=warnings,
    )


def review_candidates(candidates: list[Candidate]) -> list[Verdict]:
    """Verdict per candidate, preserving input order."""
    return [review_candidate(c) for c in candidates]
