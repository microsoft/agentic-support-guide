"""Error-mapping tests.

Agent Framework wraps provider failures via `raise ... from ex`, so these
tests build the real cause chain. A test that classified a bare
`RateLimitError` would pass while production silently bucketed every
throttle as a generic provider error.
"""

from __future__ import annotations

import pytest

from app.foundry_agents.error_mapping import map_provider_error
from app.foundry_agents.errors import (
    AuthError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRunError,
    FoundryTimeoutError,
    ThrottledError,
)


class ChatClientException(Exception):
    """Stand-in with the same wrapping shape agent_framework uses."""


class RateLimitError(Exception):
    status_code = 429


class AuthenticationError(Exception):
    status_code = 401


class PermissionDeniedError(Exception):
    status_code = 403


class APITimeoutError(Exception):
    pass


class OpenAIContentFilterException(Exception):
    pass


def _wrapped(inner: Exception) -> Exception:
    """Reproduce `raise ChatClientException(...) from inner`."""

    try:
        try:
            raise inner
        except Exception as exc:
            raise ChatClientException(f"service failed: {exc}") from exc
    except ChatClientException as outer:
        return outer


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        (RateLimitError("429 too many requests"), ThrottledError),
        (AuthenticationError("401 unauthorized"), AuthError),
        (PermissionDeniedError("403 forbidden"), AuthError),
        (APITimeoutError("timed out"), FoundryTimeoutError),
        (OpenAIContentFilterException("blocked"), ContentFilterError),
        (ValueError("something else"), FoundryRunError),
    ],
)
def test_wrapped_exceptions_classify_through_cause(
    inner: Exception, expected: type[FoundryProviderError]
) -> None:
    mapped = map_provider_error(_wrapped(inner))
    assert isinstance(mapped, expected)


def test_asyncio_timeout_maps_to_timeout() -> None:
    assert isinstance(map_provider_error(TimeoutError()), FoundryTimeoutError)


def test_already_mapped_error_passes_through() -> None:
    original = ThrottledError("THROTTLED", "slow down")
    assert map_provider_error(original) is original


def test_mapped_errors_never_leak_provider_text() -> None:
    secret = "prompt text and endpoint https://secret.example.invalid"
    mapped = map_provider_error(_wrapped(ValueError(secret)))
    assert secret not in mapped.safe_message
    assert "secret.example.invalid" not in str(mapped)


def test_auth_message_mentions_rbac_propagation() -> None:
    """Learners hit this on first run; the message must tell them what to do."""

    mapped = map_provider_error(_wrapped(AuthenticationError("401")))
    assert "az login" in mapped.safe_message
    assert "RBAC" in mapped.safe_message
