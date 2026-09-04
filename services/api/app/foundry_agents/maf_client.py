"""The only module that imports Microsoft Agent Framework SDK symbols.

Keeping the import surface here means the rest of the app depends on the
`maf_runtime` interface, and a drift test can assert that persisted-agent
symbols are never imported anywhere.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .errors import ConfigurationError, FoundryRunError
from .maf_runtime import RoleDefinition


@dataclass(frozen=True)
class ChatResult:
    text: str
    parsed: Any
    # The deployment that actually served the call. With a model router this
    # differs from the deployment name that was requested.
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class FoundryResponsesClientFactory:
    """Builds and invokes a MAF Agent per call.

    `store=False` is set on every call: the OpenAI Responses client used under
    the hood stores by default, and this prototype must not leave response
    bodies server-side.
    """

    def __init__(self, *, project_endpoint: str, credential_factory: Any) -> None:
        if not project_endpoint:
            raise ConfigurationError(
                "PROJECT_ENDPOINT_MISSING",
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.",
            )
        self._project_endpoint = project_endpoint
        self._credential_factory = credential_factory

    async def __call__(
        self,
        definition: RoleDefinition,
        user_message: str,
        response_model: type[BaseModel] | None,
    ) -> ChatResult:
        from agent_framework import Agent
        from agent_framework.foundry import FoundryChatClient

        credential = self._credential_factory()
        try:
            client = FoundryChatClient(
                project_endpoint=self._project_endpoint,
                model=definition.model_deployment,
                credential=credential,
            )
            options: dict[str, Any] = {"store": False}
            if definition.temperature is not None:
                options["temperature"] = definition.temperature
            if response_model is not None:
                options["response_format"] = response_model

            async with Agent(
                client=client,
                name=definition.role,
                instructions=definition.instructions,
            ) as agent:
                response = await agent.run(user_message, options=options)
        finally:
            await aclose_foundry_client(client)
            await _aclose(credential)

        text = str(getattr(response, "text", "") or "")
        parsed = _safe_value(response)
        if parsed is None and not text:
            raise FoundryRunError(
                "EMPTY_RESPONSE",
                "Remote agent returned no content.",
            )
        return ChatResult(
            text=text,
            parsed=parsed,
            model=_served_model(response) or definition.model_deployment,
            input_tokens=_usage(response, "input_token_count"),
            output_tokens=_usage(response, "output_token_count"),
        )


def _served_model(response: Any) -> str:
    """`AgentResponse` has no model field; the underlying `ChatResponse` does."""

    raw = getattr(response, "raw_representation", None)
    for candidate in (response, raw):
        model = getattr(candidate, "model", None)
        if isinstance(model, str) and model:
            return model
    return ""


def _usage(response: Any, key: str) -> int | None:
    """`usage_details` is a mapping, not an object - getattr silently misses."""

    usage = getattr(response, "usage_details", None)
    if usage is None:
        raw = getattr(response, "raw_representation", None)
        usage = getattr(raw, "usage_details", None)
    if isinstance(usage, Mapping):
        value = usage.get(key)
        return value if isinstance(value, int) else None
    value = getattr(usage, key, None)
    return value if isinstance(value, int) else None


async def _aclose(obj: Any) -> None:
    close = getattr(obj, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def aclose_foundry_client(client: Any) -> None:
    """Release a FoundryChatClient's HTTP sessions.

    `FoundryChatClient` has no `close()`, and exiting `async with Agent(...)`
    leaves its inner `AsyncOpenAI` open (verified: `is_closed()` is False
    afterwards). The sessions hang off `.client` and `.project_client`.
    """

    if client is None:
        return
    for attr in ("client", "project_client"):
        await _aclose(getattr(client, attr, None))
    await _aclose(client)


def _safe_value(response: Any) -> Any:
    """`.value` re-parses the structured output and can raise on bad JSON.

    Returning None on failure is what makes the raw-text fallback reachable.
    """

    try:
        return getattr(response, "value", None)
    except Exception:  # noqa: BLE001 - fall back to parsing text
        return None


def default_credential_factory() -> Any:
    """Async credential - the Foundry client wraps an async project client."""

    from azure.identity.aio import DefaultAzureCredential

    return DefaultAzureCredential()
