"""Microsoft Agent Framework runtime for the three agent roles.

Each role is a `agent_framework.Agent` backed by `FoundryChatClient`, which
calls the Foundry project's Responses API. This is the local development
inner loop: instructions are composed from `/agents/<id>/agent.md` once at
application construction and cached here, so a prompt edit takes effect on
the next process start with no publish step.

Publishing the same definitions to Foundry as prompt agents is a separate
GenAIOps step - see `python/scripts/publish_prompt_agents.py`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from .error_mapping import map_provider_error
from .errors import ConfigurationError, FoundryProviderError

# Value recorded on traces and audit rows. Single source of truth; a drift
# test asserts nothing else hardcodes it.
PROVIDER_ID = "azure_foundry_responses"


@dataclass(frozen=True)
class RoleResponse:
    role: str
    text: str
    parsed: Any
    # Deployment that served the call. Differs from the requested deployment
    # when a model router is in front.
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)


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
    ) -> None:
        self._roles = roles
        self._client_factory = client_factory

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
    ) -> RoleResponse:
        definition = self._roles.get(role)
        if definition is None:
            raise ConfigurationError(
                "ROLE_NOT_CONFIGURED",
                f"Role '{role}' has no model deployment configured.",
            )

        try:
            # No session/conversation id: every role call is isolated so prior
            # agent output can never leak in as conversation history.
            result = await self._client_factory(definition, user_message, response_model)
        except FoundryProviderError:
            raise
        except asyncio.CancelledError:
            # Shutdown/cancellation must propagate, not become a provider error.
            raise
        except Exception as exc:
            raise map_provider_error(exc) from exc

        return RoleResponse(
            role=role,
            text=result.text,
            parsed=result.parsed,
            model=getattr(result, "model", "") or definition.model_deployment,
            input_tokens=getattr(result, "input_tokens", None),
            output_tokens=getattr(result, "output_tokens", None),
        )
