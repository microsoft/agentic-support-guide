"""Test doubles for the Foundry integration.

Nothing here talks to Azure. `FakeFoundryClient` implements the same
duck-typed surface as `FoundryAgentClient` but drives run responses
from an in-memory table keyed by role.

Roles are resolved through the same binding file mechanism the runtime
uses, so tests exercise the same lookup path as production.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.foundry_agents import (
    AgentBinding,
    ContentFilterError,
    FoundryRemoteAgentAdapter,
    FoundryRunError,
    FoundryTimeoutError,
    RunResult,
    ThrottledError,
    hash_endpoint,
)
from app.foundry_agents.sdk_client import RemoteAgent

DEFAULT_ENDPOINT = "https://fake-foundry.example.invalid/api/projects/asg"


class FakeFoundryClient:
    """In-memory replacement for FoundryAgentClient.

    Callers register responses per (role_or_assistant_id, sequence-slot)
    and each `run_agent` call pops the next queued response.
    """

    def __init__(self) -> None:
        self._agents: dict[str, RemoteAgent] = {}
        self._queues: dict[str, list[str | Exception]] = defaultdict(list)
        self._calls: list[dict[str, Any]] = []
        self._create_count = 0
        self.list_agents_calls = 0

    # -- test helpers -------------------------------------------------
    def register_response(self, assistant_id: str, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._queues[assistant_id].append(payload)

    def register_error(self, assistant_id: str, exc: Exception) -> None:
        self._queues[assistant_id].append(exc)

    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

    # -- FoundryAgentClient duck-typed surface ------------------------
    def list_agents(self) -> list[dict[str, Any]]:
        self.list_agents_calls += 1
        return [{"id": a.id, "name": a.name, "model": a.model} for a in self._agents.values()]

    def create_agent(
        self,
        *,
        name: str,
        model: str,
        instructions: str,
        temperature: float | None,
        response_format: dict[str, Any] | str | None,
    ) -> RemoteAgent:
        self._create_count += 1
        assistant_id = f"asst_fake_{self._create_count}"
        mode = _mode_from_response_format(response_format)
        agent = RemoteAgent(
            id=assistant_id,
            name=name,
            model=model,
            instructions=instructions,
            temperature=temperature,
            response_format_mode=mode,
        )
        self._agents[assistant_id] = agent
        return agent

    def update_agent(
        self,
        assistant_id: str,
        *,
        name: str | None = None,
        model: str | None = None,
        instructions: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> RemoteAgent:
        prev = self._agents.get(assistant_id)
        mode = (
            _mode_from_response_format(response_format)
            if response_format is not None
            else (prev.response_format_mode if prev else "unknown")
        )
        agent = RemoteAgent(
            id=assistant_id,
            name=name or (prev.name if prev else assistant_id),
            model=model or (prev.model if prev else "unknown"),
            instructions=instructions or (prev.instructions if prev else ""),
            temperature=(
                temperature if temperature is not None else (prev.temperature if prev else None)
            ),
            response_format_mode=mode,
        )
        self._agents[assistant_id] = agent
        return agent

    def get_agent(self, assistant_id: str) -> RemoteAgent:
        return self._agents[assistant_id]

    def run_agent(
        self,
        *,
        assistant_id: str,
        user_message: str,
        run_timeout_seconds: float,
    ) -> RunResult:
        self._calls.append(
            {
                "assistant_id": assistant_id,
                "user_message": user_message,
                "run_timeout_seconds": run_timeout_seconds,
            }
        )
        queue = self._queues[assistant_id]
        if not queue:
            raise FoundryRunError(
                "NO_FAKE_RESPONSE",
                f"No fake response queued for {assistant_id}.",
            )
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return RunResult(
            thread_id="thread_fake",
            run_id="run_fake",
            assistant_message=item,
            latency_ms=1,
        )


def _mode_from_response_format(fmt: dict[str, Any] | str | None) -> str:
    if fmt is None:
        return "unknown"
    if fmt == "json_object":
        return "json_object"
    if isinstance(fmt, dict):
        t = fmt.get("type")
        if t == "json_object":
            return "json_object"
        if t == "json_schema":
            return "json_schema"
    return "unknown"


def build_bindings(
    *,
    project_endpoint: str = DEFAULT_ENDPOINT,
    analyst_id: str = "asst_fake_analyst",
    recommender_id: str = "asst_fake_recommender",
    validator_id: str = "asst_fake_validator",
) -> dict[str, AgentBinding]:
    endpoint_hash = hash_endpoint(project_endpoint)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "data-analyst-agent": AgentBinding(
            role="data-analyst-agent",
            assistant_id=analyst_id,
            agent_name="asg-data-analyst-agent",
            model="fake-analyst-model",
            instructions_hash="0" * 64,
            manifest_version="1.0.0",
            response_format_mode="json_object",
            project_endpoint_hash=endpoint_hash,
            updated_at=now,
        ),
        "support-recommendation-agent": AgentBinding(
            role="support-recommendation-agent",
            assistant_id=recommender_id,
            agent_name="asg-support-recommendation-agent",
            model="fake-recommender-model",
            instructions_hash="0" * 64,
            manifest_version="1.0.0",
            response_format_mode="json_object",
            project_endpoint_hash=endpoint_hash,
            updated_at=now,
        ),
        "validator-agent": AgentBinding(
            role="validator-agent",
            assistant_id=validator_id,
            agent_name="asg-validator-agent",
            model="fake-validator-model",
            instructions_hash="0" * 64,
            manifest_version="1.0.0",
            response_format_mode="json_object",
            project_endpoint_hash=endpoint_hash,
            updated_at=now,
        ),
    }


def make_fake_adapter(
    client: FakeFoundryClient,
    *,
    project_endpoint: str = DEFAULT_ENDPOINT,
    bindings: dict[str, AgentBinding] | None = None,
    run_timeout_seconds: float = 5.0,
) -> FoundryRemoteAgentAdapter:
    return FoundryRemoteAgentAdapter(
        client=client,
        bindings=(
            bindings if bindings is not None else build_bindings(project_endpoint=project_endpoint)
        ),
        project_endpoint=project_endpoint,
        run_timeout_seconds=run_timeout_seconds,
    )


__all__ = [
    "DEFAULT_ENDPOINT",
    "ContentFilterError",
    "FakeFoundryClient",
    "FoundryRunError",
    "FoundryTimeoutError",
    "ThrottledError",
    "build_bindings",
    "make_fake_adapter",
    "time",
]
