"""Role-agnostic remote adapter for Azure AI Foundry agents.

Given a role name and a user message, it invokes the bound remote
assistant and returns the assistant's raw text. Roles are resolved
through the local bindings file. All SDK calls go through
FoundryAgentClient.

This adapter never falls back to the base model, never runs locally,
and never invents a response. If bindings are missing the caller must
handle ConfigurationError.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bindings import AgentBinding, hash_endpoint
from .errors import ConfigurationError, FoundryProviderError
from .sdk_client import FoundryAgentClientProtocol


@dataclass(frozen=True)
class RemoteAgentResponse:
    role: str
    assistant_id: str
    text: str
    latency_ms: int
    thread_id: str
    run_id: str


class FoundryRemoteAgentAdapter:
    def __init__(
        self,
        *,
        client: FoundryAgentClientProtocol,
        bindings: dict[str, AgentBinding],
        project_endpoint: str,
        run_timeout_seconds: float,
    ) -> None:
        self._client = client
        self._bindings = bindings
        self._project_endpoint_hash = hash_endpoint(project_endpoint)
        self._run_timeout_seconds = run_timeout_seconds

    @property
    def bindings(self) -> dict[str, AgentBinding]:
        return self._bindings

    def is_bound(self, role: str) -> bool:
        return role in self._bindings and bool(self._bindings[role].assistant_id)

    def all_roles_bound(self, roles: tuple[str, ...]) -> bool:
        return all(self.is_bound(r) for r in roles)

    def invoke(self, *, role: str, user_message: str) -> RemoteAgentResponse:
        binding = self._bindings.get(role)
        if binding is None or not binding.assistant_id:
            raise ConfigurationError(
                "AGENT_NOT_BOUND",
                f"Role '{role}' is not bound to a remote Foundry agent.",
            )
        if (
            binding.project_endpoint_hash
            and binding.project_endpoint_hash != self._project_endpoint_hash
        ):
            raise ConfigurationError(
                "BINDING_ENDPOINT_MISMATCH",
                (
                    f"Bindings for role '{role}' were produced against a "
                    "different Foundry project endpoint. Re-run the sync "
                    "script with --rebind."
                ),
            )
        try:
            result = self._client.run_agent(
                assistant_id=binding.assistant_id,
                user_message=user_message,
                run_timeout_seconds=self._run_timeout_seconds,
            )
        except FoundryProviderError:
            raise
        return RemoteAgentResponse(
            role=role,
            assistant_id=binding.assistant_id,
            text=result.assistant_message,
            latency_ms=result.latency_ms,
            thread_id=result.thread_id,
            run_id=result.run_id,
        )
