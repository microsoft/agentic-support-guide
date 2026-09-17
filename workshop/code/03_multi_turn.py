"""Sample 3 — a session carries conversation history.

    python workshop/code/03_multi_turn.py

Mirrors https://learn.microsoft.com/agent-framework/get-started/multi-turn

`agent.run(...)` with no session is stateless: every call starts from nothing.
Pass the same session twice and the second call can see the first.

This sample does both, so you can watch "it" resolve in one case and fail in
the other. Session state is also the reason a real service cannot share one
conversation between two users -- each caller needs their own.
"""

from __future__ import annotations

import asyncio

from _shared import banner, chat_client
from agent_framework import Agent

FOLLOW_UP = "Which of those would you do first?"


async def main() -> None:
    async with (
        chat_client() as client,
        Agent(
            client=client,
            name="support-explainer",
            instructions=(
                "You explain dealership sales-process problems to a general manager. "
                "Answer in at most three sentences."
            ),
        ) as agent,
    ):
        banner("Sample 3 — no session, so the follow-up has no referent")
        await agent.run("Name two causes of slow first reply to online enquiries.")
        stateless = await agent.run(FOLLOW_UP)
        print(stateless.text)

        banner("Sample 3 — same session, so the follow-up resolves")
        session = agent.create_session()
        await agent.run(
            "Name two causes of slow first reply to online enquiries.",
            session=session,
        )
        stateful = await agent.run(FOLLOW_UP, session=session)
        print(stateful.text)


if __name__ == "__main__":
    asyncio.run(main())
