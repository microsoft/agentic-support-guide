"""Input and output safety for the hosted agent.

Separate from main.py so it can be unit-tested without booting the
Responses server (which initialises telemetry and probes Azure IMDS).

This exists because the hosted agent runs standalone: it never reaches the
API's coordinator or validator agent, so it has to enforce the domain rule
itself. `SafetyGate` is Agent Framework agent middleware, so it applies to
every call the host makes, streamed or not.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable

from agent_framework import (
    AgentContext,
    AgentMiddleware,
    AgentResponse,
    AgentResponseUpdate,
    Content,
    Message,
    MiddlewareTermination,
    ResponseStream,
)
from determinations import (
    HUMAN_REVIEW_CAVEAT,
    asserts_determination,
    denies_human_review,
)
from prompt_blocks import wrap_untrusted

# The endpoint is internet-reachable, so it bounds its own input.
QUESTION_MAX_LEN = 2000
# Hard ceiling on what is collected before the cap above is applied.
# Generous next to a real question, small next to a crafted payload.
_COLLECT_MAX_CHARS = 200_000

EMPTY_QUESTION_REPLY = "Ask a question about dealership support practice."

__all__ = [
    "EMPTY_QUESTION_REPLY",
    "HUMAN_REVIEW_CAVEAT",
    "QUESTION_MAX_LEN",
    "SafetyGate",
    "asserts_determination",
    "bounded_question",
    "gate",
    "plain_text",
]


def bounded_question(texts: Iterable[str]) -> str:
    """Join the request's text, bounded before it is normalised.

    Collection stops once the ceiling is passed, so a request with many
    content blocks cannot make this endpoint normalise megabytes it was
    always going to throw away.
    """

    collected: list[str] = []
    total = 0
    for text in texts:
        if not text:
            continue
        collected.append(text)
        total += len(text)
        if total > _COLLECT_MAX_CHARS:
            break
    return "\n".join(collected)[:_COLLECT_MAX_CHARS].strip()[:QUESTION_MAX_LEN]


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


class SafetyGate(AgentMiddleware):
    """Decides what reaches the model, and what comes back from it.

    In: only this request's text, bounded and fenced as untrusted data. No
    session, so nothing from an earlier turn reaches the model, and no caller
    options, so a caller cannot swap the model, the instructions or the tools.
    Out: the deterministic gate over the whole answer. A streamed answer is
    held until it is complete, because a gate that sees half an answer
    cannot withhold the other half.
    """

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        question = bounded_question(message.text for message in context.messages)
        if not question:
            # A fixed reply, and no model call.
            raise MiddlewareTermination(result=_reply(EMPTY_QUESTION_REPLY, stream=context.stream))

        context.messages = [Message("user", [wrap_untrusted("user question", question)])]
        context.session = None
        context.options = None

        if context.stream:
            context.stream_buffer_updates = True
            context.stream_result_to_updates = _as_updates
            context.stream_result_transforms.append(_gated)
            await call_next()
            return

        await call_next()
        if isinstance(context.result, AgentResponse):
            context.result = _gated(context.result)


def _gated(response: AgentResponse) -> AgentResponse:
    return AgentResponse(
        messages=[Message("assistant", [gate(response.text)])],
        response_id=response.response_id,
        created_at=response.created_at,
        finish_reason=response.finish_reason,
        usage_details=response.usage_details,
    )


def _as_updates(response: AgentResponse) -> list[AgentResponseUpdate]:
    return [
        AgentResponseUpdate(
            contents=list(message.contents),
            role=message.role,
            response_id=response.response_id,
            message_id=message.message_id,
        )
        for message in response.messages
    ]


def _reply(
    text: str, *, stream: bool
) -> AgentResponse | ResponseStream[AgentResponseUpdate, AgentResponse]:
    if not stream:
        return AgentResponse(messages=[Message("assistant", [text])])

    async def updates() -> AsyncIterator[AgentResponseUpdate]:
        yield AgentResponseUpdate(contents=[Content.from_text(text)], role="assistant")

    return ResponseStream(updates(), finalizer=AgentResponse.from_updates)
