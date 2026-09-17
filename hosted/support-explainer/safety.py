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

from determinations import (
    HUMAN_REVIEW_CAVEAT,
    asserts_determination,
    denies_human_review,
)

# The endpoint is internet-reachable, so it bounds its own input.
QUESTION_MAX_LEN = 2000
# Hard ceiling on what is collected and normalised before the cap above is
# applied. Generous next to a real question, small next to a crafted payload.
_WALK_MAX_CHARS = 200_000

__all__ = [
    "HUMAN_REVIEW_CAVEAT",
    "QUESTION_MAX_LEN",
    "asserts_determination",
    "extract_question",
    "gate",
    "plain_text",
]


def extract_question(request: object) -> str:
    """Pull the bounded, fenced user text out of a Responses request.

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
                if sum(len(p) for p in found) > _WALK_MAX_CHARS:
                    break
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
    # Clipped before sanitising, not after. `walk` bounded depth but not
    # breadth, so a request with many content blocks made this endpoint
    # normalise megabytes it was always going to throw away.
    return joined[:_WALK_MAX_CHARS].strip()[:QUESTION_MAX_LEN]


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


def gate(answer: str) -> str:
    """Deterministic output check, because no validator agent runs here."""

    text = plain_text(answer)
    if asserts_determination(text) or denies_human_review(text):
        return (
            "That response was withheld because it read as a determination "
            "this system must never make. " + HUMAN_REVIEW_CAVEAT
        )
    # Matching the caveat itself, not the words "human review", because
    # "No human review is needed." satisfied the looser check and was then
    # returned untouched — with the caveat suppressed.
    if HUMAN_REVIEW_CAVEAT in text:
        return text
    return f"{text}\n\n{HUMAN_REVIEW_CAVEAT}"
