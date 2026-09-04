"""Input and output safety for the hosted agent.

Separate from main.py so it can be unit-tested without booting the
Responses server (which initialises telemetry and probes Azure IMDS).

This exists because the hosted agent runs standalone: it never reaches the
API's coordinator or validator agent, so it has to enforce the domain rule
itself.
"""

from __future__ import annotations

import json
import re

from sanitization import sanitize_free_text

# The endpoint is internet-reachable, so it bounds its own input.
QUESTION_MAX_LEN = 2000

HUMAN_REVIEW_CAVEAT = (
    "A human must review this before acting on it. This is synthetic guidance "
    "and is not an educational, clinical, legal, disability, or placement "
    "determination."
)

_FORBIDDEN_OUTPUT = re.compile(
    r"\b(diagnos(is|es|e|ed|ing)|placement decision|eligib(le|ility) for an? (iep|504)"
    r"|legal determination|medical determination|policy determination"
    r"|must be placed)\b",
    re.IGNORECASE,
)

# Refusals, hedges and deferrals that make a nearby match legitimate rather
# than an assertion by this system.
_NEGATED_OR_DEFERRED = re.compile(
    r"\b(not|never|cannot|can't|isn't|is not|avoid|without|rather than|"
    r"may|might|would|should|qualified|clinician|specialist|professional|"
    r"human review|refer|diagnostic)\b",
    re.IGNORECASE,
)


def extract_question(request: object) -> str:
    """Pull sanitized user text out of a Responses request.

    The handler receives the request as a plain dict, and `input` is a bare
    string or a list of messages/content blocks depending on the caller, so
    this walks the structure instead of assuming one shape.
    """

    def walk(node: object, depth: int = 0) -> list[str]:
        if depth > 6:
            return []
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                return [node["text"]]
            return walk(node.get("content"), depth + 1)
        if isinstance(node, (list, tuple)):
            found: list[str] = []
            for child in node:
                found.extend(walk(child, depth + 1))
            return found
        text = getattr(node, "text", None)
        if isinstance(text, str):
            return [text]
        content = getattr(node, "content", None)
        if content is not None:
            return walk(content, depth + 1)
        return []

    raw = request.get("input") if isinstance(request, dict) else getattr(request, "input", None)
    joined = "\n".join(p for p in walk(raw) if p).strip()
    return sanitize_free_text(joined, max_len=QUESTION_MAX_LEN)


def plain_text(answer: str) -> str:
    """Unwrap a fenced JSON payload so a caveat is not appended to JSON.

    This agent's contract is plain language, but models often over-format
    into ```json {"answer": ...}```. Appending prose to that would produce
    something neither a human nor a parser can use.
    """

    stripped = answer.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return answer
        if isinstance(payload, dict):
            for key in ("answer", "text", "response"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return answer


def asserts_determination(text: str) -> bool:
    """True only for assertions, so refusals and hedges are not withheld.

    "This is not a diagnosis" and "a clinician may diagnose" are correct,
    desirable sentences; withholding them would punish the safe answer.
    """

    for match in _FORBIDDEN_OUTPUT.finditer(text):
        window = text[max(0, match.start() - 60) : match.end() + 20].lower()
        if _NEGATED_OR_DEFERRED.search(window):
            continue
        return True
    return False


def gate(answer: str) -> str:
    """Deterministic output check, because no validator agent runs here."""

    text = plain_text(answer)
    if asserts_determination(text):
        return (
            "That response was withheld because it read as a determination "
            "this system must never make. " + HUMAN_REVIEW_CAVEAT
        )
    if "human review" in text.lower():
        return text
    return f"{text}\n\n{HUMAN_REVIEW_CAVEAT}"
