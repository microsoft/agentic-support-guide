"""Prompt-injection sanitization helpers.

Used by the coordinator before any user or prior-agent text reaches an LLM.
"""

from __future__ import annotations

import re

# Delimit any untrusted block using stable ASCII tags. The prompts instruct
# the model to treat anything inside these tags as data, never instructions.
DATA_OPEN = "<<<UNTRUSTED_DATA>>>"
DATA_CLOSE = "<<<END_UNTRUSTED_DATA>>>"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all )?previous instructions", re.IGNORECASE),
    re.compile(r"disregard the (?:above|system) prompt", re.IGNORECASE),
    re.compile(r"you are now .{0,60}", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"forget (?:all )?prior (?:guidance|instructions)", re.IGNORECASE),
    re.compile(r"new instructions\s*:", re.IGNORECASE),
)

# Format enforced on LLM-produced warning/issue codes before they can appear
# anywhere the UI could render them. Requires uppercase snake case with a
# minimum length of 4 characters so short freeform tokens like "OK" or "NO"
# never survive.
CODE_REGEX = re.compile(r"^[A-Z][A-Z0-9_]{3,59}$")


def sanitize_free_text(text: str, *, max_len: int) -> str:
    """Strip control chars, collapse the injection-attack surface, and clip."""

    cleaned = _CONTROL_CHARS.sub(" ", text or "")
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[filtered]", cleaned)
    cleaned = cleaned.replace(DATA_OPEN, "[filtered]").replace(DATA_CLOSE, "[filtered]")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


def wrap_untrusted(label: str, body: str) -> str:
    return f"{DATA_OPEN} kind={label}\n{body}\n{DATA_CLOSE}"


def enforce_code(candidate: str) -> str | None:
    """Return the candidate iff it looks like a stable machine code."""

    if not isinstance(candidate, str):
        return None
    trimmed = candidate.strip()
    if CODE_REGEX.fullmatch(trimmed):
        return trimmed
    return None
