"""Microsoft Agent Framework runtime for the three agent roles.

Each role is a `agent_framework.Agent` backed by `FoundryChatClient`, which
calls the Foundry project's Responses API. This is the local development
inner loop: instructions are composed from `/agents/<id>/agent.md` once at
application construction and cached here, so a prompt edit takes effect on
the next process start with no publish step.

Publishing the same definitions to Foundry as prompt agents is a separate
GenAIOps step - see `scripts/publish_prompt_agents.py`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from .error_mapping import map_provider_error
from .errors import ConfigurationError, FoundryProviderError

# Value recorded on traces and audit rows. Single source of truth; a drift
# test asserts nothing else hardcodes it.
PROVIDER_ID = "azure_foundry_responses"

_MIN_RUN_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class CallMetrics:
    role: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


# Task-local, so concurrent requests sharing one runtime never interleave.
_run_calls: ContextVar[list[CallMetrics] | None] = ContextVar("maf_run_calls", default=None)


@contextmanager
def collect_call_metrics() -> Iterator[list[CallMetrics]]:
    """Record every provider call made inside this block."""

    calls: list[CallMetrics] = []
    token = _run_calls.set(calls)
    try:
        yield calls
    finally:
        _run_calls.reset(token)


@dataclass(frozen=True)
class RoleResponse:
    role: str
    text: str
    parsed: Any
    latency_ms: int
    # Deployment that served the call. Differs from the requested deployment
    # when a model router is in front.
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatClientProtocol(Protocol):
    """Minimal surface the runtime needs, so tests can substitute a fake."""

    async def get_response(self, messages: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class RoleDefinition:
    role: str
    instructions: str
    model_deployment: str
    temperature: float | None
    max_output_tokens: int | None = None


class MafAgentRuntime:
    """Runs a role's single-turn call against Foundry via Agent Framework."""

    def __init__(
        self,
        *,
        roles: dict[str, RoleDefinition],
        client_factory: Any,
        run_timeout_seconds: float,
    ) -> None:
        self._roles = roles
        self._client_factory = client_factory
        self._run_timeout_seconds = run_timeout_seconds

    @property
    def roles(self) -> dict[str, RoleDefinition]:
        return self._roles

    def has_role(self, role: str) -> bool:
        return role in self._roles

    def all_roles_available(self, roles: tuple[str, ...]) -> bool:
        return all(self.has_role(r) for r in roles)

    async def invoke(
        self,
        *,
        role: str,
        user_message: str,
        response_model: type[BaseModel] | None = None,
        deadline: float | None = None,
    ) -> RoleResponse:
        definition = self._roles.get(role)
        if definition is None:
            raise ConfigurationError(
                "ROLE_NOT_CONFIGURED",
                f"Role '{role}' has no model deployment configured.",
            )

        started = time.monotonic()
        timeout = self._effective_run_timeout(deadline)
        try:
            # No session/conversation id: every role call is isolated so prior
            # agent output can never leak in as conversation history.
            result = await asyncio.wait_for(
                self._client_factory(definition, user_message, response_model),
                timeout=timeout,
            )
        except FoundryProviderError:
            raise
        except asyncio.CancelledError:
            # Shutdown/cancellation must propagate, not become a provider error.
            raise
        except Exception as exc:
            raise map_provider_error(exc) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        model = getattr(result, "model", "") or definition.model_deployment
        input_tokens = getattr(result, "input_tokens", None)
        output_tokens = getattr(result, "output_tokens", None)

        sink = _run_calls.get()
        if sink is not None:
            sink.append(
                CallMetrics(
                    role=role,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )
            )

        return RoleResponse(
            role=role,
            text=result.text,
            parsed=result.parsed,
            latency_ms=latency_ms,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _effective_run_timeout(self, deadline: float | None) -> float:
        """Clamp the per-run timeout to what is left of the orchestration budget."""

        if deadline is None:
            return self._run_timeout_seconds
        remaining = deadline - time.monotonic()
        return max(_MIN_RUN_TIMEOUT_SECONDS, min(self._run_timeout_seconds, remaining))
