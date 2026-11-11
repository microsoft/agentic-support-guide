"""Hosted agent: the Support Explainer, running as Foundry-managed code.

Same role as the Module 4 prompt agent, same instructions file. The
difference is where it runs and what it can do: this process is built and
run by Foundry, gets its own Entra identity, and can carry any dependency
in requirements.txt.

Foundry starts this with `python main.py` and routes Responses-protocol
traffic to it. `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and
`FOUNDRY_MODEL_DEPLOYMENT` arrive as environment variables set at deploy
time; the credential resolves to the agent's own identity, not yours.

Input sanitising and the output gate live in safety.py so they can be
tested without booting this server.
"""

from __future__ import annotations

import os
from pathlib import Path

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from prompt_blocks import wrap_untrusted
from safety import extract_question, gate

INSTRUCTIONS_FILE = Path(__file__).with_name("instructions.md")

app = ResponsesAgentServerHost()


def _instructions() -> str:
    return INSTRUCTIONS_FILE.read_text(encoding="utf-8")


async def _answer(question: str) -> str:
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient
    from azure.identity.aio import DefaultAzureCredential

    endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ["FOUNDRY_MODEL_DEPLOYMENT"]

    credential = DefaultAzureCredential()
    client = None
    try:
        client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
        async with Agent(
            client=client, name="support-explainer", instructions=_instructions()
        ) as agent:
            result = await agent.run(
                wrap_untrusted("user question", question), options={"store": False}
            )
        return str(getattr(result, "text", "") or "")
    finally:
        # Exiting the Agent context does NOT close the chat client's inner
        # sessions, and this process is long-lived, so they would accumulate.
        for obj in (
            getattr(client, "client", None),
            getattr(client, "project_client", None),
            credential,
        ):
            close = getattr(obj, "close", None)
            if close is None:
                continue
            closing = close()
            if hasattr(closing, "__await__"):
                await closing


@app.response_handler
async def handle(request, context, cancellation_signal):  # noqa: ANN001, ANN201
    question = extract_question(request)
    if not question:
        answer = "Ask a question about dealership support practice."
    else:
        answer = gate(await _answer(question))
    async for event in TextResponse(context, request, text=answer):
        yield event


if __name__ == "__main__":
    # Foundry health-checks and routes to this port.
    app.run(port=int(os.environ.get("PORT", "8088")))
