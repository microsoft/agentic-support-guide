"""What the production client factory puts on the wire.

The fakes in the other tests replace the client factory, so nothing else
checks the request Agent Framework actually sends. This runs the real factory
against a local HTTP server that records the request and answers with a
canned Responses API reply.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from azure.core.credentials import AccessToken, AccessTokenInfo

from app.agents.shared.contracts import DataAnalystModelOutput
from app.foundry_agents.maf_client import FoundryResponsesClientFactory
from app.foundry_agents.maf_runtime import RoleDefinition
from app.foundry_agents.prompt_envelope import load_agent_assets, load_response_schema

REPLY_TEXT = '{"ok": true}'


class _Recorder(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    reply_model = "served-deployment"
    served_model_header: str | None = None

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        length = int(self.headers.get("content-length", "0"))
        _Recorder.requests.append(json.loads(self.rfile.read(length) or b"{}"))
        payload = json.dumps(
            {
                "id": "resp_test",
                "object": "response",
                "created_at": 1700000000,
                "status": "completed",
                "model": _Recorder.reply_model,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": REPLY_TEXT, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        if _Recorder.served_model_header is not None:
            self.send_header("x-ms-served-model", _Recorder.served_model_header)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        return


class _StaticCredential:
    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("test-token", 4102444800)

    async def get_token_info(self, *scopes: str, options: Any = None) -> AccessTokenInfo:
        return AccessTokenInfo("test-token", 4102444800)

    async def close(self) -> None:
        return None


@pytest.fixture
def endpoint() -> Iterator[str]:
    _Recorder.requests = []
    _Recorder.reply_model = "served-deployment"
    _Recorder.served_model_header = None
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/projects/asg"
    finally:
        server.shutdown()


def _definition() -> RoleDefinition:
    return RoleDefinition(
        role="data-analyst-agent",
        instructions="Analyse things.",
        model_deployment="fake-deployment",
        temperature=0.2,
        max_output_tokens=800,
        response_schema=load_response_schema(load_agent_assets("data-analyst")),
    )


def test_every_call_disables_storage_and_sends_the_agent_folder_schema(endpoint: str) -> None:
    factory = FoundryResponsesClientFactory(
        project_endpoint=endpoint, credential_factory=_StaticCredential
    )
    result = asyncio.run(factory(_definition(), "hello", DataAnalystModelOutput))

    [request] = _Recorder.requests
    assert request["store"] is False
    assert request["model"] == "fake-deployment"
    assert request["instructions"] == "Analyse things."
    assert request["temperature"] == 0.2
    assert request["max_output_tokens"] == 800
    assert request["input"][0]["content"][0]["text"] == "hello"
    assert request["text"]["format"] == {
        "type": "json_schema",
        "name": "DataAnalystModelOutput",
        "schema": _definition().response_schema,
        "strict": True,
    }
    assert (result.text, result.model, result.input_tokens, result.output_tokens) == (
        REPLY_TEXT,
        "served-deployment",
        11,
        7,
    )


def test_an_off_contract_reply_is_returned_for_the_app_to_judge(endpoint: str) -> None:
    """Agent Framework must not reject it first, or it becomes a provider error."""

    factory = FoundryResponsesClientFactory(
        project_endpoint=endpoint, credential_factory=_StaticCredential
    )
    result = asyncio.run(factory(_definition(), "hello", DataAnalystModelOutput))
    assert result.text == REPLY_TEXT


@pytest.mark.parametrize(
    ("deployment", "body_model", "header", "expected"),
    [
        # What Foundry returned for each, measured: an ordinary deployment
        # echoes its own name in the body and names the snapshot in the header.
        ("asg-chat", "asg-chat", "gpt-4.1-mini-2025-04-14", "gpt-4.1-mini-2025-04-14"),
        # A router names itself in the header and the model it picked in the body.
        ("asg-router", "gpt-5-nano-2025-08-07", "model-router-2025-11-18", "gpt-5-nano-2025-08-07"),
    ],
    ids=["ordinary-deployment", "model-router"],
)
def test_the_trace_names_the_model_that_answered(
    endpoint: str, deployment: str, body_model: str, header: str, expected: str
) -> None:
    _Recorder.reply_model = body_model
    _Recorder.served_model_header = header
    factory = FoundryResponsesClientFactory(
        project_endpoint=endpoint, credential_factory=_StaticCredential
    )
    definition = replace(_definition(), model_deployment=deployment)
    result = asyncio.run(factory(definition, "hello", DataAnalystModelOutput))
    assert result.model == expected
