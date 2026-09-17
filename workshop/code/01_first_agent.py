"""Sample 1 — an agent is a model plus instructions.

    python workshop/code/01_first_agent.py

Mirrors https://learn.microsoft.com/agent-framework/get-started/your-first-agent

That is the whole idea. `Agent` wraps a chat client and a system prompt, and
`run` sends one message. Everything else in this workshop is added on top of
these six lines.
"""

from __future__ import annotations

import asyncio

from _shared import banner, chat_client
from agent_framework import Agent

INSTRUCTIONS = """
You explain dealership sales-process problems to a general manager.
Answer in at most three sentences. Plain language, no jargon.
"""


async def main() -> None:
    async with (
        chat_client() as client,
        Agent(
            client=client,
            name="support-explainer",
            instructions=INSTRUCTIONS,
        ) as agent,
    ):
        banner("Sample 1 — first agent")
        response = await agent.run(
            "Our median first reply to an online enquiry has slipped past one hour. "
            "Why does that matter?"
        )
        print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
