"""Test doubles for the Agent Framework runtime.

Nothing here talks to Azure. The fake stands in for the client factory the
runtime calls, so tests exercise the real `MafAgentRuntime` - including its
timeout clamping, error mapping, and role resolution - without a network.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from app.foundry_agents.maf_client import ChatResult
from app.foundry_agents.maf_runtime import MafAgentRuntime, RoleDefinition
from app.foundry_agents.role_definitions import REQUIRED_ROLES

DEFAULT_ENDPOINT = "https://fake-foundry.example.invalid/api/projects/asg"
DEFAULT_DEPLOYMENT = "fake-deployment"


class FakeChatClientFactory:
    """Records every call and returns queued responses per role."""

    def __init__(self) -> None:
        self._queues: dict[str, list[str | Exception]] = defaultdict(list)
        self._calls: list[dict[str, Any]] = []

    def register_response(self, role: str, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._queues[role].append(payload)

    def register_error(self, role: str, exc: Exception) -> None:
        self._queues[role].append(exc)

    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

    async def __call__(
        self,
        definition: RoleDefinition,
        user_message: str,
        response_model: type[BaseModel] | None,
    ) -> ChatResult:
        # Mirrors the production factory, which always disables server-side
        # storage. Tests assert on this.
        self._calls.append(
            {
                "role": definition.role,
                "model": definition.model_deployment,
                "instructions": definition.instructions,
                "user_message": user_message,
                "response_model": response_model,
                "store": False,
                "temperature": definition.temperature,
            }
        )
        queue = self._queues[definition.role]
        if not queue:
            raise AssertionError(f"no fake response queued for role {definition.role!r}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        parsed: Any = None
        if response_model is not None:
            try:
                parsed = response_model.model_validate_json(item)
            except Exception:  # noqa: BLE001 - lets tests exercise the text fallback
                parsed = None
        return ChatResult(text=item, parsed=parsed)


def build_role_definitions(
    *, instructions: str = "test instructions", temperature: float | None = 0.2
) -> dict[str, RoleDefinition]:
    return {
        role: RoleDefinition(
            role=role,
            instructions=instructions,
            model_deployment=DEFAULT_DEPLOYMENT,
            temperature=temperature,
        )
        for role in REQUIRED_ROLES
    }


def make_fake_runtime(
    factory: FakeChatClientFactory | None = None,
    *,
    roles: dict[str, RoleDefinition] | None = None,
    run_timeout_seconds: float = 30.0,
) -> tuple[MafAgentRuntime, FakeChatClientFactory]:
    factory = factory or FakeChatClientFactory()
    runtime = MafAgentRuntime(
        roles=roles if roles is not None else build_role_definitions(),
        client_factory=factory,
        run_timeout_seconds=run_timeout_seconds,
    )
    return runtime, factory
