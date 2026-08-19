"""Thin wrapper around the azure-ai-agents SDK.

This is the ONLY module in the app that imports from azure.ai.agents.
Everything else consumes the small typed interface exposed here.

If the installed SDK version does not support an operation the app
needs, this module raises ConfigurationError or NotImplementedError
with a safe message. It never silently falls back to the base model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import (
    AuthError,
    ConfigurationError,
    ContentFilterError,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    ThrottledError,
)


@dataclass(frozen=True)
class RemoteAgent:
    id: str
    name: str
    model: str
    instructions: str
    temperature: float | None
    response_format_mode: str


@dataclass(frozen=True)
class RunResult:
    thread_id: str
    run_id: str
    assistant_message: str
    latency_ms: int


class FoundryAgentClientProtocol(Protocol):
    """Stable interface used by the rest of the app."""

    def list_agents(self) -> list[dict[str, Any]]: ...

    def create_agent(
        self,
        *,
        name: str,
        model: str,
        instructions: str,
        temperature: float | None,
        response_format: dict[str, Any] | str | None,
    ) -> RemoteAgent: ...

    def update_agent(
        self,
        assistant_id: str,
        *,
        name: str | None = None,
        model: str | None = None,
        instructions: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> RemoteAgent: ...

    def get_agent(self, assistant_id: str) -> RemoteAgent: ...

    def run_agent(
        self,
        *,
        assistant_id: str,
        user_message: str,
        run_timeout_seconds: float,
    ) -> RunResult: ...


class FoundryAgentClient:
    """Concrete implementation backed by azure-ai-agents.AgentsClient."""

    def __init__(self, *, endpoint: str, credential: Any) -> None:
        try:
            from azure.ai.agents import AgentsClient
        except ImportError as exc:
            raise ConfigurationError(
                "SDK_NOT_INSTALLED",
                "azure-ai-agents is not installed. Install requirements.",
            ) from exc
        self._endpoint = endpoint
        self._client = AgentsClient(endpoint=endpoint, credential=credential)

    def close(self) -> None:
        self._client.close()

    def list_agents(self) -> list[dict[str, Any]]:
        try:
            return [
                {"id": a.id, "name": a.name, "model": a.model} for a in self._client.list_agents()
            ]
        except Exception as exc:  # noqa: BLE001 - map to safe typed error
            raise _map_provider_error(exc) from exc

    def create_agent(
        self,
        *,
        name: str,
        model: str,
        instructions: str,
        temperature: float | None,
        response_format: dict[str, Any] | str | None,
    ) -> RemoteAgent:
        kwargs: dict[str, Any] = {
            "name": name,
            "model": model,
            "instructions": instructions,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response_format_arg, mode = _prepare_response_format(response_format)
        if response_format_arg is not None:
            kwargs["response_format"] = response_format_arg
        try:
            agent = self._client.create_agent(**kwargs)
        except Exception as exc:
            mapped = _map_response_format_fallback(exc, response_format_arg)
            if mapped == "fallback_json_object":
                kwargs["response_format"] = "json_object"
                mode = "json_object"
                agent = self._client.create_agent(**kwargs)
            else:
                raise _map_provider_error(exc) from exc
        return _to_remote_agent(agent, mode)

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
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if model is not None:
            kwargs["model"] = model
        if instructions is not None:
            kwargs["instructions"] = instructions
        if temperature is not None:
            kwargs["temperature"] = temperature
        response_format_arg, mode = _prepare_response_format(response_format)
        if response_format_arg is not None:
            kwargs["response_format"] = response_format_arg
        try:
            agent = self._client.update_agent(assistant_id, **kwargs)
        except Exception as exc:
            mapped = _map_response_format_fallback(exc, response_format_arg)
            if mapped == "fallback_json_object":
                kwargs["response_format"] = "json_object"
                mode = "json_object"
                agent = self._client.update_agent(assistant_id, **kwargs)
            else:
                raise _map_provider_error(exc) from exc
        return _to_remote_agent(agent, mode)

    def get_agent(self, assistant_id: str) -> RemoteAgent:
        try:
            agent = self._client.get_agent(assistant_id)
        except Exception as exc:
            raise _map_provider_error(exc) from exc
        return _to_remote_agent(agent, "unknown")

    def run_agent(
        self,
        *,
        assistant_id: str,
        user_message: str,
        run_timeout_seconds: float,
    ) -> RunResult:
        started = time.monotonic()
        thread_id: str | None = None
        run_id: str | None = None
        try:
            thread = self._client.threads.create()
            thread_id = thread.id
            self._client.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message,
            )
            run = self._client.runs.create(thread_id=thread_id, agent_id=assistant_id)
            run_id = run.id
            terminal_run = self._poll_run(thread_id, run_id, run_timeout_seconds)
            # Classify terminal status FIRST so a failed/expired/requires_action
            # run raises the correct typed error rather than a downstream
            # NO_ASSISTANT_MESSAGE when the model produced no text.
            self._map_terminal_status(terminal_run)
            content = self._read_last_assistant_text(thread_id)
        except Exception as exc:
            if isinstance(
                exc,
                FoundryTimeoutError | FoundryRunError | RequiresActionError | ContentFilterError,
            ):
                if thread_id and run_id:
                    self._safe_cancel(thread_id, run_id)
                raise
            raise _map_provider_error(exc) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        return RunResult(
            thread_id=thread_id or "",
            run_id=run_id or "",
            assistant_message=content,
            latency_ms=latency_ms,
        )

    def _poll_run(self, thread_id: str, run_id: str, budget_seconds: float) -> Any:
        deadline = time.monotonic() + budget_seconds
        delay = 1.0
        while True:
            try:
                run = self._client.runs.get(thread_id, run_id)
            except Exception as exc:
                raise _map_provider_error(exc) from exc
            status = str(getattr(run, "status", "unknown")).lower()
            if status in {"completed", "failed", "cancelled", "expired", "requires_action"}:
                return run
            if time.monotonic() > deadline:
                raise FoundryTimeoutError(
                    "RUN_TIMEOUT",
                    (
                        "Remote agent run did not reach a terminal state within "
                        f"{budget_seconds:.0f}s."
                    ),
                )
            time.sleep(delay)
            delay = min(5.0, delay * 1.5)

    def _read_last_assistant_text(self, thread_id: str) -> str:
        try:
            msg = self._client.messages.get_last_message_by_role(
                thread_id=thread_id,
                role="assistant",  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise _map_provider_error(exc) from exc
        if msg is None:
            raise FoundryRunError(
                "NO_ASSISTANT_MESSAGE",
                "Remote agent did not produce an assistant message.",
            )
        # ThreadMessage.content is a list of MessageTextContent | ... blocks.
        chunks: list[str] = []
        for block in getattr(msg, "content", []) or []:
            text = getattr(block, "text", None)
            value = getattr(text, "value", None) if text is not None else None
            if value:
                chunks.append(str(value))
        return "".join(chunks) if chunks else ""

    def _safe_cancel(self, thread_id: str, run_id: str) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self._client.runs.cancel(thread_id, run_id)

    @staticmethod
    def _map_terminal_status(run: Any) -> None:
        status = str(getattr(run, "status", "unknown")).lower()
        last_error = getattr(run, "last_error", None)
        error_code = str(getattr(last_error, "code", "")).lower() if last_error else ""
        error_message = getattr(last_error, "message", "") if last_error else ""
        if status == "completed":
            return
        if status == "requires_action":
            raise RequiresActionError(
                "REQUIRES_ACTION",
                "Remote agent requires tool actions. Not supported in this build.",
            )
        if status == "expired":
            raise FoundryTimeoutError("RUN_EXPIRED", "Remote agent run expired.")
        if "content_filter" in error_code or "content_filter" in error_message.lower():
            raise ContentFilterError(
                "CONTENT_FILTER",
                "Remote agent request was blocked by content safety.",
            )
        if status in {"failed", "cancelled"}:
            raise FoundryRunError(
                "RUN_FAILED",
                f"Remote agent run ended in status {status}.",
            )
        raise FoundryRunError(
            "UNKNOWN_RUN_STATUS",
            f"Remote agent run ended in unknown status: {status}.",
        )


def _prepare_response_format(
    fmt: dict[str, Any] | str | None,
) -> tuple[Any, str]:
    if fmt is None:
        return None, "unknown"
    if fmt == "json_object":
        return {"type": "json_object"}, "json_object"
    if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
        return fmt, "json_schema"
    return fmt, "unknown"


def _map_response_format_fallback(exc: Exception, response_format_arg: Any) -> str:
    """Return 'fallback_json_object' iff exc looks like a json_schema rejection."""

    if response_format_arg is None:
        return ""
    msg = str(exc).lower()
    if "response_format" in msg and ("unsupported" in msg or "invalid" in msg):
        return "fallback_json_object"
    if "json_schema" in msg and "not supported" in msg:
        return "fallback_json_object"
    return ""


def _to_remote_agent(agent: Any, response_format_mode: str) -> RemoteAgent:
    return RemoteAgent(
        id=str(agent.id),
        name=str(getattr(agent, "name", "") or ""),
        model=str(getattr(agent, "model", "") or ""),
        instructions=str(getattr(agent, "instructions", "") or ""),
        temperature=getattr(agent, "temperature", None),
        response_format_mode=response_format_mode,
    )


def _map_provider_error(exc: Exception) -> Exception:
    """Classify SDK exceptions into safe typed provider errors."""

    if isinstance(exc, FoundryTimeoutError | FoundryRunError | RequiresActionError):
        return exc
    status = getattr(exc, "status_code", None)
    msg = str(exc)
    lower = msg.lower()
    if status in (401, 403) or "forbidden" in lower or "unauthorized" in lower:
        return AuthError("AUTH_DENIED", "Foundry rejected credential (RBAC or endpoint).")
    if status == 429 or "throttled" in lower or "rate limit" in lower:
        return ThrottledError("THROTTLED", "Foundry throttled the request.")
    if "content_filter" in lower:
        return ContentFilterError(
            "CONTENT_FILTER",
            "Remote agent request was blocked by content safety.",
        )
    if status == 404 or "not found" in lower:
        return FoundryRunError("NOT_FOUND", "Requested Foundry resource was not found.")
    return FoundryRunError("PROVIDER_ERROR", "Foundry provider returned an error.")
