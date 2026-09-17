"""Sample 6 — agents can be steps in a workflow.

    python workshop/code/06_agents_in_a_workflow.py

Mirrors https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential

Sample 5's executors were plain Python. Swap two of them for agents and you
have **sequential orchestration**: agents in a fixed order, each working on
what the one before it produced.

An agent can be passed straight to `add_edge`; Agent Framework wraps it so
its response arrives at the next step as an `AgentExecutorResponse`. That
carries three things: `executor_id`, `agent_response` (what this agent said),
and `full_conversation` (everything so far).

Two details that bite:

- **A wrapped agent yields output too.** By default every agent in the graph
  publishes its response, so `get_outputs()` would return three things and
  `[0]` would be the *analyst*, not the answer. `output_from=[finalise]`
  names the one step whose output is the workflow's result.
- **The default context mode forwards the whole conversation.** The
  recommender here receives the original dealership record as well as the
  analyst's finding, because `AgentExecutor` chains `full_conversation`. If
  you want a step to see only what the previous step said -- which is often
  the point of splitting them up -- you have to say so explicitly. This
  sample keeps the default and tells you, rather than claiming an isolation
  it does not have.

Agent Framework also ships `SequentialBuilder` for a pure agent pipeline like
this one. It is in the separate `agent-framework-orchestrations` package, and
it builds a straight line. Sample 7 needs an edge that goes backwards, which
a straight line cannot express -- so this workshop uses `WorkflowBuilder`
throughout and you only learn one API.
"""

from __future__ import annotations

import asyncio
from typing import Never

from _shared import banner, chat_client
from agent_framework import (
    AgentExecutorResponse,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    executor,
)

DEALERSHIP = (
    "DLR-0001, volume segment. lead-response 41/100 and falling for three months. "
    "test-drive-conversion 63/100 and flat. Appointments attended 72%."
)


def build_workflow(client):
    analyst = client.as_agent(
        name="analyst",
        instructions=(
            "You read dealership process scores. State the single most important "
            "finding and the evidence for it, in two sentences. Recommend nothing."
        ),
    )
    recommender = client.as_agent(
        name="recommender",
        instructions=(
            "You turn a finding into one concrete action a general manager can "
            "take this week. Two sentences. Do not restate the finding."
        ),
    )

    @executor(id="finalise")
    async def finalise(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(response.agent_response.text)

    return (
        WorkflowBuilder(
            start_executor=analyst,
            name="support-plan",
            # Without this, every agent's response is also an output.
            output_from=[finalise],
        )
        .add_edge(analyst, recommender)
        .add_edge(recommender, finalise)
        .build()
    )


async def main() -> None:
    async with chat_client() as client:
        workflow = build_workflow(client)

        banner("Sample 6 — draw it first")
        print(WorkflowViz(workflow).to_mermaid())

        banner("Sample 6 — then run it")
        events = await workflow.run(DEALERSHIP)
        outputs = events.get_outputs()
        print(f"{len(outputs)} output(s)")
        print(outputs[0])


if __name__ == "__main__":
    asyncio.run(main())
