"""Sample 5 — a workflow is executors joined by edges.

    python workshop/code/05_first_workflow.py

Mirrors https://learn.microsoft.com/agent-framework/get-started/workflows

No model, no Azure, no network. Run this one offline.

Three pieces, and that is the entire model:

    EXECUTOR   a step. Either a class with an @handler, or a plain async
               function with @executor.
    EDGE       source -> target. The target runs when the source sends it
               a message.
    WORKFLOW   WorkflowBuilder(start_executor=...).add_edge(...).build()

Inside an executor you use `ctx` to do either or both of:

    ctx.send_message(x)   pass x along the outgoing edges
    ctx.yield_output(x)   publish x as one of the workflow's results

The type parameter on `WorkflowContext` declares which types each is allowed
to carry. `WorkflowContext[str]` sends a str onward. `WorkflowContext[Never,
str]` sends nothing onward and yields a str -- `Never` is how "this step
forwards nothing" is written. It is a statement about types, not a stop
instruction: a step that yields an output *and* sends a message will still
have its successors run.

The payoff is the last few lines: because the workflow is data rather than
control flow, `WorkflowViz` can draw it. You cannot draw an if-statement.
"""

from __future__ import annotations

import asyncio
from typing import Never

from _shared import banner
from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    executor,
    handler,
)


class Normalise(Executor):
    """A class-based executor. One @handler per input type it accepts."""

    @handler
    async def run(self, concern: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(" ".join(concern.split()).lower())


@executor(id="classify")
async def classify(concern: str, ctx: WorkflowContext[str]) -> None:
    """A function-based executor. Same thing, less ceremony."""

    area = "lead-response" if "reply" in concern or "enquiry" in concern else "general"
    await ctx.send_message(f"{area}: {concern}")


@executor(id="summarise")
async def summarise(tagged: str, ctx: WorkflowContext[Never, str]) -> None:
    """Last step: yields the workflow's output instead of sending one on."""

    await ctx.yield_output(f"routed -> {tagged}")


def build_workflow():
    normalise = Normalise(id="normalise")
    return (
        WorkflowBuilder(start_executor=normalise, name="triage")
        .add_edge(normalise, classify)
        .add_edge(classify, summarise)
        .build()
    )


async def main() -> None:
    workflow = build_workflow()

    banner("Sample 5 — run it")
    events = await workflow.run("  Our first REPLY to an online enquiry is   slow ")
    print(events.get_outputs()[0])

    banner("Sample 5 — draw it")
    # Paste this into any Markdown file that renders Mermaid.
    print(WorkflowViz(workflow).to_mermaid())


if __name__ == "__main__":
    asyncio.run(main())
