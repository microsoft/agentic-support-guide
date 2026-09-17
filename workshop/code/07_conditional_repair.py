"""Sample 7 — a conditional edge can send work back.

    python workshop/code/07_conditional_repair.py

Mirrors the conditional-edge half of
https://learn.microsoft.com/agent-framework/concepts/workflows/

**This is the shape the whole application uses.** Module 3 picks it up.

Sample 6 was a straight line. Real work is not: sometimes a step produces
something that is not good enough, and you want one more try rather than a
failure. That is a third argument to `add_edge`:

    .add_edge(source, target, condition=lambda msg: ...)

The edge is only followed when the condition returns True. Two conditions out
of the same node are a branch. A condition on an edge pointing *back* is a
bounded loop.

Here the validator either accepts a draft, or sends it back once with a
reason attached:

    retrieve -> recommend -> validate -+-> accept        (passed)
                    ^                  |
                    +------------------+                (failed, 1st time)
                                       |
                                       +-> give_up      (failed twice)

Four rules worth copying:

- **Messages are values, never mutated.** `Draft` is frozen and every step
  returns a new one with `replace()`. This is the first bug people hit here.
  Several outgoing edges are handed the *same* message object and evaluate
  their conditions independently; if the repair target mutates that object
  first, a sibling condition then sees the new state and fires too. An
  earlier version of this file did exactly that and yielded two answers for
  one run -- accepting and refusing the same draft.
- **The validator is plain Python.** It is a set-membership test over ids the
  retriever produced. A second model asked "is this well cited?" would be an
  opinion; `in` is an answer.
- **The loop is bounded by data, not by hope.** `Draft.attempts` travels in
  the message, and the repair condition checks it. `WorkflowBuilder` also
  takes `max_iterations`, but that is a runaway guard, not your retry policy.
- **Failing twice does not produce output.** `give_up` yields a refusal, not
  a recommendation. A workflow that returns something plausible when it could
  not do the job is worse than one that returns nothing.

No model and no network, so this runs offline. The stub recommender decides
what to do from a tag in the concern text rather than at random, so one run
walks all three paths and you can see each of them every time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Never

from _shared import banner
from agent_framework import WorkflowBuilder, WorkflowContext, WorkflowViz, executor

ALLOWED_CITATIONS = ("EV-101", "EV-102", "EV-103")
MAX_ATTEMPTS = 2

# Which attempts the stub recommender invents a citation on. Stands in for a
# model that sometimes gets it wrong, without the randomness that would make
# this file behave differently every run.
NEVER_INVENTS = "[clean]"
INVENTS_ONCE = "[repairable]"
ALWAYS_INVENTS = "[unfixable]"


@dataclass(frozen=True)
class Draft:
    """What travels along the edges. Frozen, so no step can surprise another."""

    concern: str
    allowed: tuple[str, ...] = ()
    text: str = ""
    cited: tuple[str, ...] = ()
    attempts: int = 0
    repair_reason: str = ""
    issues: tuple[str, ...] = ()


def invents_on(concern: str, attempt: int) -> bool:
    """Stands in for a model's unreliability, made reproducible."""

    if ALWAYS_INVENTS in concern:
        return True
    if INVENTS_ONCE in concern:
        return attempt == 1
    return False


@executor(id="retrieve")
async def retrieve(concern: str, ctx: WorkflowContext[Draft]) -> None:
    """Grounding happens first, in code. Sample 4 is this step in full."""

    await ctx.send_message(Draft(concern=concern, allowed=ALLOWED_CITATIONS))


@executor(id="recommend")
async def recommend(draft: Draft, ctx: WorkflowContext[Draft]) -> None:
    """Stands in for an agent. Sample 6 shows the real thing."""

    attempts = draft.attempts + 1
    invented = invents_on(draft.concern, attempts)
    await ctx.send_message(
        replace(
            draft,
            attempts=attempts,
            # An id the retriever never returned: exactly the failure a real
            # model makes.
            cited=("EV-999",) if invented else ("EV-101", "EV-102"),
            text="Assign a named advisor to every online enquiry.",
        )
    )


@executor(id="validate")
async def validate(draft: Draft, ctx: WorkflowContext[Draft]) -> None:
    """Deterministic checks. No model, no opinion."""

    allowed = set(draft.allowed)
    issues = tuple(c for c in draft.cited if c not in allowed)
    await ctx.send_message(
        replace(
            draft,
            issues=issues,
            repair_reason=f"Cite only {', '.join(draft.allowed)}." if issues else "",
        )
    )


@executor(id="accept")
async def accept(draft: Draft, ctx: WorkflowContext[Never, str]) -> None:
    await ctx.yield_output(
        f"OK after {draft.attempts} attempt(s): {draft.text} {list(draft.cited)}"
    )


@executor(id="give_up")
async def give_up(draft: Draft, ctx: WorkflowContext[Never, str]) -> None:
    """No recommendation. A typed refusal is the honest answer."""

    await ctx.yield_output(
        f"REFUSED after {draft.attempts} attempt(s): unknown citations {list(draft.issues)}"
    )


def passed(draft: Draft) -> bool:
    return not draft.issues


def needs_repair(draft: Draft) -> bool:
    return bool(draft.issues) and draft.attempts < MAX_ATTEMPTS


def exhausted(draft: Draft) -> bool:
    return bool(draft.issues) and draft.attempts >= MAX_ATTEMPTS


def build_workflow():
    """The whole workflow. Six lines, and every rule is one of them."""

    return (
        WorkflowBuilder(start_executor=retrieve, name="support-plan")
        .add_edge(retrieve, recommend)
        .add_edge(recommend, validate)
        .add_edge(validate, accept, condition=passed)
        .add_edge(validate, recommend, condition=needs_repair)
        .add_edge(validate, give_up, condition=exhausted)
        .build()
    )


async def main() -> None:
    workflow = build_workflow()

    banner("Sample 7 — draw it")
    print(WorkflowViz(workflow).to_mermaid())
    print(
        "\nThe renderer labels every conditional edge 'conditional'. Which\n"
        "condition is which is in build_workflow(): passed, needs_repair,\n"
        "exhausted. A diagram shows you the shape, not the rules."
    )

    banner("Sample 7 — all three paths")
    for label, tag in (
        ("accepted first time", NEVER_INVENTS),
        ("repaired, then accepted", INVENTS_ONCE),
        ("repair exhausted", ALWAYS_INVENTS),
    ):
        events = await workflow.run(f"{tag} First reply to online enquiries is slow.")
        outputs = events.get_outputs()
        # Exactly one, always. Two would mean a condition fired that should not.
        result = outputs[0] if len(outputs) == 1 else f"BUG: {len(outputs)} outputs {outputs}"
        print(f"  {label:24} -> {result}")


if __name__ == "__main__":
    asyncio.run(main())
