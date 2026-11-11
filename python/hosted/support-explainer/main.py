"""Hosted agent: the Support Explainer, running as Foundry-managed code.

Same role as the Module 4 prompt agent, same instructions file. The
difference is where it runs and what it can do: this process is built and
run by Foundry, gets its own Entra identity, and can carry any dependency
in requirements.txt.

Agent Framework's `ResponsesHostServer` serves the agent over the Responses
protocol; Foundry starts it with `python main.py`.
`AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL_DEPLOYMENT` arrive as
environment variables set at deploy time; the credential resolves to the
agent's own identity, not yours.

The input bounds and the output gate are `SafetyGate`, in safety.py, so they
can be tested without booting this server.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity.aio import DefaultAzureCredential
from safety import SafetyGate

agent = Agent(
    client=FoundryChatClient(
        project_endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["FOUNDRY_MODEL_DEPLOYMENT"],
        credential=DefaultAzureCredential(),
    ),
    name="support-explainer",
    instructions=Path(__file__).with_name("instructions.md").read_text(encoding="utf-8"),
    middleware=[SafetyGate()],
    # The model service keeps nothing either.
    default_options={"store": False},
)

# "agent": the host passes the agent only this request's input, and history
# would be the agent's own business. SafetyGate gives it none.
server = ResponsesHostServer(agent, history_source="agent")

if __name__ == "__main__":
    # Foundry health-checks and routes to this port.
    server.run(port=int(os.environ.get("PORT", "8088")))
