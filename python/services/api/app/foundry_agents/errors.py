"""Typed errors used across the Foundry integration.

None of these errors carry raw model text. They're used to map SDK
failures into safe, coded application errors that the coordinator can
surface without leaking prompts/completions or endpoint details.
"""

from __future__ import annotations


class FoundryProviderError(Exception):
    """Generic Foundry provider failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.safe_message = message


class ConfigurationError(FoundryProviderError):
    """Foundry project/agents are not configured."""


class FoundryTimeoutError(FoundryProviderError):
    """The remote run did not finish within the configured budget."""


class FoundryRunError(FoundryProviderError):
    """The remote run finished in a non-completed state (failed/cancelled/expired)."""


class RequiresActionError(FoundryProviderError):
    """The remote run entered requires_action. Not supported in this build."""


class ContentFilterError(FoundryProviderError):
    """The provider blocked the request via content safety."""


class ThrottledError(FoundryProviderError):
    """The provider throttled the request (429/quota)."""


class AuthError(FoundryProviderError):
    """The provider rejected the credential (401/403)."""
