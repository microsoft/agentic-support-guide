"""Sample 2 — a tool is a Python function the model may call.

    python workshop/code/02_add_tools.py

Mirrors https://learn.microsoft.com/agent-framework/get-started/add-tools

Sample 1 could only talk about what it already knew. A tool lets the model
reach for a fact. You pass ordinary Python functions in `tools=`; the type
hints and the docstring become the schema the model sees, so the annotations
are not decoration.

The model decides whether to call a tool. Watch what happens when you ask it
something the tool cannot answer -- it should say so rather than invent a
number. That choice is the model's, which is exactly why later modules stop
relying on it.

`get_process_score` only reads, so it needs no gate. A tool that **writes or
takes an action** -- books an appointment, changes a price, sends an email --
should be declared `@tool(approval_mode="always_require")`, which pauses the
run for a human to approve the specific call before it happens.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from _shared import banner, chat_client
from agent_framework import Agent

# Stand-in for a real dealer management system.
_SCORES = {
    "DLR-0001": {"lead-response": 41, "test-drive-conversion": 63},
    "DLR-0002": {"lead-response": 78, "test-drive-conversion": 71},
}


def get_process_score(
    dealership_id: Annotated[str, "Dealership id, for example DLR-0001"],
    process_area: Annotated[str, "One of: lead-response, test-drive-conversion"],
) -> str:
    """Return this month's process score (0-100) for one dealership and area."""

    scores = _SCORES.get(dealership_id)
    if scores is None:
        return f"No such dealership: {dealership_id}"
    if process_area not in scores:
        return f"No score recorded for {process_area}"
    return f"{dealership_id} {process_area}: {scores[process_area]}/100"


async def main() -> None:
    async with (
        chat_client() as client,
        Agent(
            client=client,
            name="support-explainer",
            instructions=(
                "You explain dealership sales-process problems to a general manager. "
                "Use the get_process_score tool for any question about a specific "
                "dealership's numbers. Never state a score you did not retrieve."
            ),
            tools=[get_process_score],
        ) as agent,
    ):
        banner("Sample 2 — the tool is called")
        answered = await agent.run("How is DLR-0001 doing on lead response?")
        print(answered.text)

        banner("Sample 2 — no tool can answer this")
        refused = await agent.run("How is DLR-9999 doing on lead response?")
        print(refused.text)


if __name__ == "__main__":
    asyncio.run(main())
