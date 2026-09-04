"""Map Microsoft Agent Framework / OpenAI failures onto the app error taxonomy.

`agent_framework_openai` wraps almost every provider failure in a generic
`ChatClientException` via `raise ... from ex`. Classifying the raised exception
directly therefore always lands in the generic bucket - the original
`openai` error is only reachable through `__cause__`. Content-filter failures
are the one case that surfaces as a dedicated type.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .errors import (
    AuthError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRunError,
    FoundryTimeoutError,
    ThrottledError,
)

# Walk a bounded number of __cause__ links so a nested wrap still classifies.
_MAX_CAUSE_DEPTH = 5


def _causes(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = [exc]
    current: BaseException | None = exc
    for _ in range(_MAX_CAUSE_DEPTH):
        current = getattr(current, "__cause__", None)
        if current is None:
            break
        chain.append(current)
    return chain


def _class_names(chain: list[BaseException]) -> set[str]:
    names: set[str] = set()
    for item in chain:
        for klass in type(item).__mro__:
            names.add(klass.__name__)
    return names


def _status_code(chain: list[BaseException]) -> int | None:
    for item in chain:
        code: Any = getattr(item, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _text(chain: list[BaseException]) -> str:
    return " ".join(str(item) for item in chain).lower()


def map_provider_error(exc: BaseException) -> FoundryProviderError:
    """Classify a MAF/OpenAI exception without leaking provider text."""

    if isinstance(exc, FoundryProviderError):
        return exc

    chain = _causes(exc)
    names = _class_names(chain)
    text = _text(chain)
    status = _status_code(chain)

    # Content filter is raised as its own type and is not wrapped generically.
    if "ContentFilterException" in " ".join(names) or "content_filter" in text:
        return ContentFilterError(
            "CONTENT_FILTER",
            "Remote agent request was blocked by content safety.",
        )

    if isinstance(exc, TimeoutError | asyncio.TimeoutError) or "APITimeoutError" in names:
        return FoundryTimeoutError(
            "RUN_TIMEOUT",
            "Remote agent run did not finish within the configured budget.",
        )

    if "RateLimitError" in names or status == 429:
        return ThrottledError(
            "THROTTLED",
            "Remote agent request was throttled. Retry shortly.",
        )

    if (
        names & {"AuthenticationError", "PermissionDeniedError"}
        or status in (401, 403)
        # RBAC assignments take minutes to propagate; learners hit this first.
        or "does not have authorization" in text
    ):
        return AuthError(
            "AUTH_DENIED",
            (
                "Azure rejected the credential. Run 'az login', confirm the "
                "subscription, and allow a few minutes for RBAC propagation."
            ),
        )

    return FoundryRunError("PROVIDER_ERROR", "Remote agent call failed.")
