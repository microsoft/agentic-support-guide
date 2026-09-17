"""Provider and parse failures mapped to the API's status taxonomy."""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..foundry_agents.errors import (
    AuthError,
    ConfigurationError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    ThrottledError,
)

PROVIDER_ERROR_TO_STATUS: dict[type[FoundryProviderError], tuple[str, str]] = {
    ConfigurationError: ("provider_missing", "AGENT_PROVIDER_MISSING"),
    AuthError: ("provider_error", "AGENT_PROVIDER_AUTH_DENIED"),
    ThrottledError: ("provider_throttling", "AGENT_PROVIDER_THROTTLING"),
    ContentFilterError: ("provider_content_filter", "AGENT_PROVIDER_CONTENT_FILTER"),
    FoundryTimeoutError: ("provider_timeout", "AGENT_PROVIDER_TIMEOUT"),
    RequiresActionError: ("provider_error", "AGENT_PROVIDER_REQUIRES_ACTION"),
    FoundryRunError: ("provider_error", "AGENT_PROVIDER_ERROR"),
}

_SAFE_MESSAGES = {
    "provider_timeout": "Remote agent run timed out.",
    "provider_throttling": "Remote agent was throttled.",
    "provider_content_filter": "Remote agent blocked the request via content safety.",
    "provider_error": "Remote agent returned an error.",
    "provider_missing": (
        "Foundry Agent Service is not configured or bindings are missing. "
        "Run scripts/validate_agent_definitions.py."
    ),
}

# Bounded set. An issue code reaches the API response and telemetry, so it
# must never be built from exception text. The trace contract restricts codes
# to ^[A-Z][A-Z0-9_]{3,59}$, so no colons or lowercase.
_INVALID_JSON_SCHEMA = "AGENT_INVALID_JSON_SCHEMA_MISMATCH"
_INVALID_JSON_DECODE = "AGENT_INVALID_JSON_NOT_JSON"
_INVALID_JSON_OTHER = "AGENT_INVALID_JSON_UNPARSEABLE"


def classify_provider_error(exc: FoundryProviderError) -> tuple[str, str]:
    """Map a typed provider error to (status, issue_code)."""

    for cls, mapping in PROVIDER_ERROR_TO_STATUS.items():
        if isinstance(exc, cls):
            return mapping
    return ("provider_error", "AGENT_PROVIDER_ERROR")


def safe_message(status: str) -> str:
    return _SAFE_MESSAGES.get(status, "Unknown remote agent error.")


def invalid_json_code(exc: Exception) -> str:
    """Classify a parse failure without echoing its message."""

    if isinstance(exc, json.JSONDecodeError):
        return _INVALID_JSON_DECODE
    if isinstance(exc, ValidationError):
        return _INVALID_JSON_SCHEMA
    return _INVALID_JSON_OTHER
