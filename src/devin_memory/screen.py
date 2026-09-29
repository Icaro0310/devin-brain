"""Quarantine gate: screens memory content before it becomes active.

Three families of checks, each returning named reasons:

- **secrets** — vendored regexes in the style of ``devin-redact.patterns``
  (copied here on purpose: no hard dependency on devin-redact in M1).
- **injection** — heuristics for prompt-injection phrasing and chat-ML
  control markers, the usual way a hostile session would try to plant
  instructions inside another agent's memory.
- **limits/shape** — size caps, tag hygiene, NUL bytes, long opaque
  base64-looking runs.

The gate is deliberately conservative: a false positive only lands the
entry in ``quarantined``, where a human can ``release`` it. It is a screen,
not a guarantee — dedicated scanners (gitleaks, devin-redact) still apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CONTENT_BYTES = 32 * 1024
MAX_TAGS = 32
TAG_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_B64_RUN = 480

# --- vendored from devin-redact.patterns (secret categories only) ----------

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    "stripe_live_key": re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    "stripe_restricted_key": re.compile(r"\bsk_restricted_[A-Za-z0-9]{16,}\b"),
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    "bearer_header": re.compile(r"[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "jwt": re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "github_fine_grained_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    "pem_private_key": re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
        r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    "env_assignment": re.compile(
        r"(?m)^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*"
        r"(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z0-9_]*"
        r"\s*=\s*\S[^\n]*"
    ),
}

# --- injection heuristics ---------------------------------------------------

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_previous_instructions": re.compile(
        r"\bignore\s+(?:all\s+|any\s+|the\s+)?"
        r"(?:previous|prior|above|earlier|preceding)\s+"
        r"(?:instructions?|prompts?|rules?|directions?)\b",
        re.IGNORECASE,
    ),
    "disregard_instructions": re.compile(
        r"\bdisregard\s+(?:all\s+|any\s+|the\s+)?"
        r"(?:previous|prior|above|earlier)\s+"
        r"(?:instructions?|prompts?|rules?)\b",
        re.IGNORECASE,
    ),
    "forget_everything": re.compile(
        r"\bforget\s+(?:everything|all\s+(?:previous|prior)\s+\w+)\b",
        re.IGNORECASE,
    ),
    "do_not_follow": re.compile(
        r"\bdo\s+not\s+(?:follow|obey|listen\s+to)\s+"
        r"(?:your|the|those|previous)\s+\w*instructions?\b",
        re.IGNORECASE,
    ),
    "system_prompt_override": re.compile(
        r"\b(?:new|override|replace)\s+system\s+prompt\b",
        re.IGNORECASE,
    ),
    "reveal_prompt": re.compile(
        r"\b(?:reveal|print|show|output|repeat)\s+(?:your|the)\s+"
        r"(?:system\s+prompt|initial\s+instructions?|hidden\s+instructions?)\b",
        re.IGNORECASE,
    ),
    "chatml_markers": re.compile(
        r"<\|(?:im_start|im_end|system|user|assistant)\|>"
    ),
    "inst_markers": re.compile(r"\[/?INST\]|<<\s*/?\s*SYS\s*>>"),
    "act_as_unrestricted": re.compile(
        r"\bact\s+as\s+(?:an?\s+)?(?:unrestricted|unfiltered|uncensored)\b",
        re.IGNORECASE,
    ),
    "jailbreak_phrase": re.compile(
        r"\b(?:jailbreak|do\s+anything\s+now|DAN\s+mode)\b", re.IGNORECASE
    ),
}

_B64_RUN = re.compile(r"\b[A-Za-z0-9+/=]{%d,}\b" % MAX_B64_RUN)


@dataclass(frozen=True)
class ScreenResult:
    status: str  # "active" | "quarantined"
    reasons: tuple[str, ...]


def _secret_reasons(content: str) -> list[str]:
    return [
        f"secret:{name}"
        for name, rx in SECRET_PATTERNS.items()
        if rx.search(content)
    ]


def _injection_reasons(content: str) -> list[str]:
    return [
        f"injection:{name}"
        for name, rx in INJECTION_PATTERNS.items()
        if rx.search(content)
    ]


def _shape_reasons(content: str, tags: list[str]) -> list[str]:
    reasons: list[str] = []
    if len(content.encode("utf-8", "surrogatepass")) > MAX_CONTENT_BYTES:
        reasons.append("limit:content_too_large")
    if len(tags) > MAX_TAGS:
        reasons.append("limit:too_many_tags")
    if any(not TAG_RE.match(t) for t in tags):
        reasons.append("shape:bad_tag")
    if "\x00" in content:
        reasons.append("shape:nul_byte")
    if _B64_RUN.search(content):
        reasons.append("shape:long_base64_run")
    return reasons


def screen(content: str, tags: list[str] | tuple[str, ...] = ()) -> ScreenResult:
    """Screen one candidate memory.

    Returns ``ScreenResult(status="quarantined", reasons=(...))`` when any
    check fires; ``status="active"`` otherwise. Reasons use a
    ``family:name`` convention (``secret:``, ``injection:``, ``limit:``,
    ``shape:``) and are stored on the entry for audit.
    """
    tag_list = list(tags)
    reasons = (
        _shape_reasons(content, tag_list)
        + _secret_reasons(content)
        + _injection_reasons(content)
    )
    return ScreenResult(
        status="quarantined" if reasons else "active",
        reasons=tuple(reasons),
    )
