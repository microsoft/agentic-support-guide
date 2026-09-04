"""Prompt-injection sanitization helpers.

Used by the coordinator before any user or prior-agent text reaches an LLM.
"""

from __future__ import annotations

import re
import unicodedata

# Delimit any untrusted block using stable ASCII tags. The prompts instruct
# the model to treat anything inside these tags as data, never instructions.
DATA_OPEN = "<<<UNTRUSTED_DATA>>>"
DATA_CLOSE = "<<<END_UNTRUSTED_DATA>>>"

_MAX_FILTER_PASSES = 4

# Upper bound for a single fenced block. Generous enough for the JSON payloads
# the agents exchange, small enough to cap prompt growth.
UNTRUSTED_BLOCK_MAX_LEN = 12000

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Zero-width and bidi-override characters, plus the Unicode word joiner. These
# let an attacker split a denylisted phrase without changing how it renders.
_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\ufeff]")
# Patterns run AFTER whitespace collapsing and invisible-char stripping.
# Word gaps use \s* (not \s+) because stripping a zero-width joiner out of
# "ignore<ZWSP>all" leaves "ignoreall" with no separator left to match.
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s*(?:all\s*)?(?:previous|prior|above)\s*instructions", re.IGNORECASE),
    re.compile(
        r"disregard\s*the\s*(?:above|system|previous)\s*(?:prompt|instructions)", re.IGNORECASE
    ),
    re.compile(r"you\s*are\s*now\s*.{0,60}", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"forget\s*(?:all\s*)?prior\s*(?:guidance|instructions)", re.IGNORECASE),
    re.compile(r"new\s*instructions\s*:", re.IGNORECASE),
)

# Format enforced on LLM-produced warning/issue codes before they can appear
# anywhere the UI could render them. Requires uppercase snake case with a
# minimum length of 4 characters so short freeform tokens like "OK" or "NO"
# never survive.
CODE_REGEX = re.compile(r"^[A-Z][A-Z0-9_]{3,59}$")


def sanitize_free_text(text: str, *, max_len: int) -> str:
    """Strip control chars, collapse the injection-attack surface, and clip."""

    # NFKC folds compatibility/fullwidth forms (e.g. "ｉｇｎｏｒｅ") onto their
    # ASCII equivalents so the denylist below cannot be dodged by codepoint
    # substitution.
    cleaned = unicodedata.normalize("NFKC", text or "")
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    cleaned = _INVISIBLE_CHARS.sub("", cleaned)
    # Collapse whitespace BEFORE matching: otherwise "ignore  all previous
    # instructions" (double space, tab, or newline) slips past every pattern.
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Re-run until stable so a payload that reconstitutes a denylisted phrase
    # after one substitution (nested injection) is also caught. Bounded so a
    # pathological input cannot spin here.
    for _ in range(_MAX_FILTER_PASSES):
        before = cleaned
        for pat in _INJECTION_PATTERNS:
            cleaned = pat.sub("[filtered]", cleaned)
        cleaned = cleaned.replace(DATA_OPEN, "[filtered]").replace(DATA_CLOSE, "[filtered]")
        if cleaned == before:
            break

    return cleaned.strip()[:max_len]


def wrap_untrusted(label: str, body: str) -> str:
    """Fence untrusted text and sanitize it in one place.

    Sanitizing here (rather than only at ingress) covers prior-agent output
    re-forwarded to a later model, which is otherwise an unfiltered hop.
    """

    safe_body = sanitize_free_text(body, max_len=UNTRUSTED_BLOCK_MAX_LEN)
    return f"{DATA_OPEN} kind={label}\n{safe_body}\n{DATA_CLOSE}"


def enforce_code(candidate: str) -> str | None:
    """Return the candidate iff it looks like a stable machine code."""

    if not isinstance(candidate, str):
        return None
    trimmed = candidate.strip()
    if CODE_REGEX.fullmatch(trimmed):
        return trimmed
    return None
