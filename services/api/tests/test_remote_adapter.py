"""Tests for the remote-agent adapter and SDK client mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.foundry_agents import (
    AgentBinding,
    ConfigurationError,
    ContentFilterError,
    FoundryAgentClient,
    FoundryRemoteAgentAdapter,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    hash_endpoint,
)

from .fakes import DEFAULT_ENDPOINT, FakeFoundryClient, build_bindings, make_fake_adapter


def _bindings_with_endpoint(endpoint_hash: str) -> dict[str, AgentBinding]:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "data-analyst-agent": AgentBinding(
            role="data-analyst-agent",
            assistant_id="asst_fake",
            agent_name="asg",
            model="m",
            instructions_hash="0" * 64,
            manifest_version="1.0.0",
            response_format_mode="json_object",
            project_endpoint_hash=endpoint_hash,
            updated_at=now,
        ),
    }


def test_adapter_invoke_routes_to_correct_assistant_id() -> None:
    client = FakeFoundryClient()
    b = build_bindings()
    client.register_response(b["data-analyst-agent"].assistant_id, {"ok": True})
    adapter = make_fake_adapter(client, bindings=b)
    resp = adapter.invoke(role="data-analyst-agent", user_message="hi")
    assert resp.assistant_id == b["data-analyst-agent"].assistant_id
    assert json.loads(resp.text) == {"ok": True}


def test_adapter_raises_configuration_error_when_role_not_bound() -> None:
    client = FakeFoundryClient()
    adapter = make_fake_adapter(client, bindings={})
    with pytest.raises(ConfigurationError):
        adapter.invoke(role="data-analyst-agent", user_message="hi")


def test_adapter_refuses_binding_from_different_endpoint() -> None:
    """Endpoint hash mismatch surfaces as ConfigurationError."""
    client = FakeFoundryClient()
    other = hash_endpoint("https://other.example.invalid/")
    b = _bindings_with_endpoint(other)
    adapter = FoundryRemoteAgentAdapter(
        client=client,
        bindings=b,
        project_endpoint=DEFAULT_ENDPOINT,
        run_timeout_seconds=1.0,
    )
    with pytest.raises(ConfigurationError) as excinfo:
        adapter.invoke(role="data-analyst-agent", user_message="hi")
    assert "BINDING_ENDPOINT_MISMATCH" in excinfo.value.code


def test_adapter_all_roles_bound() -> None:
    client = FakeFoundryClient()
    adapter = make_fake_adapter(client)
    assert adapter.all_roles_bound(
        ("data-analyst-agent", "support-recommendation-agent", "validator-agent")
    )
    empty = make_fake_adapter(client, bindings={})
    assert not empty.all_roles_bound(("data-analyst-agent",))


def test_adapter_propagates_content_filter_error() -> None:
    client = FakeFoundryClient()
    b = build_bindings()
    client.register_error(
        b["data-analyst-agent"].assistant_id,
        ContentFilterError("CONTENT_FILTER", "blocked"),
    )
    adapter = make_fake_adapter(client, bindings=b)
    with pytest.raises(ContentFilterError):
        adapter.invoke(role="data-analyst-agent", user_message="hi")


def test_adapter_propagates_timeout_error() -> None:
    client = FakeFoundryClient()
    b = build_bindings()
    client.register_error(
        b["data-analyst-agent"].assistant_id,
        FoundryTimeoutError("RUN_TIMEOUT", "timed out"),
    )
    adapter = make_fake_adapter(client, bindings=b)
    with pytest.raises(FoundryTimeoutError):
        adapter.invoke(role="data-analyst-agent", user_message="hi")


def test_adapter_propagates_requires_action_error() -> None:
    client = FakeFoundryClient()
    b = build_bindings()
    client.register_error(
        b["data-analyst-agent"].assistant_id,
        RequiresActionError("REQUIRES_ACTION", "nope"),
    )
    adapter = make_fake_adapter(client, bindings=b)
    with pytest.raises(RequiresActionError):
        adapter.invoke(role="data-analyst-agent", user_message="hi")


# ---------------------------------------------------------------------
# FoundryAgentClient wraps azure-ai-agents. Isolate its terminal-status
# mapping using a stub sdk client.
# ---------------------------------------------------------------------


def _make_wrapper() -> FoundryAgentClient:
    # Bypass the real AgentsClient constructor so tests never touch the SDK.
    wrapper = FoundryAgentClient.__new__(FoundryAgentClient)
    object.__setattr__(wrapper, "_endpoint", "https://x.example.invalid/")
    object.__setattr__(wrapper, "_client", MagicMock())
    return wrapper


def _stub(w: FoundryAgentClient) -> Any:
    return object.__getattribute__(w, "_client")


def _fake_run(status: str, *, code: str | None = None, message: str = "") -> MagicMock:
    run = MagicMock()
    run.id = "run_1"
    run.status = status
    if code:
        err = MagicMock()
        err.code = code
        err.message = message
        run.last_error = err
    else:
        run.last_error = None
    return run


def _fake_thread(thread_id: str = "thread_1") -> MagicMock:
    t = MagicMock()
    t.id = thread_id
    return t


def _fake_text_message(text: str) -> MagicMock:
    tv = MagicMock()
    tv.value = text
    block = MagicMock()
    block.text = tv
    msg = MagicMock()
    msg.content = [block]
    return msg


def test_client_completed_run_returns_message_text() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.messages.create.return_value = None
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("completed")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message('{"ok":true}')
    result = wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)
    assert result.assistant_message == '{"ok":true}'


def test_client_failed_run_raises_foundry_run_error() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("failed")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message("")
    with pytest.raises(FoundryRunError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)


def test_client_expired_run_raises_timeout_error() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("expired")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message("")
    with pytest.raises(FoundryTimeoutError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)


def test_client_requires_action_raises_typed_error() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("requires_action")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message("")
    with pytest.raises(RequiresActionError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)


def test_client_content_filter_error_mapped() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("failed", code="content_filter", message="blocked")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message("")
    with pytest.raises(ContentFilterError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)


def test_client_cancelled_run_raises_foundry_run_error() -> None:
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("cancelled")
    stub.messages.get_last_message_by_role.return_value = _fake_text_message("")
    with pytest.raises(FoundryRunError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)


def test_client_terminal_status_classified_before_reading_message() -> None:
    """Regression: a failed run must raise FoundryRunError even when
    the assistant produced no message. Previously the empty-message
    check ran first and masked the real cause."""
    wrapper = _make_wrapper()
    stub = _stub(wrapper)
    stub.threads.create.return_value = _fake_thread()
    stub.runs.create.return_value = _fake_run("queued")
    stub.runs.get.return_value = _fake_run("failed")
    # No assistant message at all - would previously raise NO_ASSISTANT_MESSAGE.
    stub.messages.get_last_message_by_role.return_value = None
    with pytest.raises(FoundryRunError):
        wrapper.run_agent(assistant_id="asst_1", user_message="hi", run_timeout_seconds=1.0)
