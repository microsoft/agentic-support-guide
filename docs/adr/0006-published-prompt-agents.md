# ADR 0006 — Published prompt agents, with the Agent Framework runtime

Status: Accepted
Date: 2026-09-03
Supersedes: [ADR 0005 — Agent Framework with ephemeral Foundry agents](0005-agent-framework-ephemeral-agents.md)

## Context

ADR 0005 moved the repo onto the real Microsoft Agent Framework and made
agents *ephemeral*: assembled in-process per call, with nothing persisted in
Foundry. That solved the portal migration prompt and the shared-namespace
problem.

It also broke the primary purpose of the repo. This codebase exists to show
people how Foundry agents work. With nothing persisted, the Foundry portal
Agents list was empty. There was no artifact to look at, no version history,
and no way to demonstrate the difference between a prompt agent and a hosted
agent — which is the central teaching point.

Optimising away a portal popup at the cost of the demo was the wrong trade.

## Decision

Keep the Agent Framework runtime **and** publish the same definitions to
Foundry as **prompt agents**.

1. **Runtime (inner loop).** `MafAgentRuntime` + `FoundryChatClient` continue
   to assemble each role in-process from `/agents/<id>/agent.md`. A prompt
   edit takes effect on the next request with no publish step.
2. **Published artifact (GenAIOps).** `scripts/publish_prompt_agents.py`
   composes the same instructions and publishes them via `to_prompt_agent` +
   `AIProjectClient.agents.create_version`. Agents are visible and versioned
   in the portal.

Both paths compose instructions through `prompt_envelope.compose_instructions`
from the same source files, so the portal shows what the app runs.

### Collision handling

Publishing reintroduces a shared server-side namespace, which is what ADR
0005 was avoiding. That is handled directly rather than by not publishing:

- `--suffix` is **required** on publish, validated `[a-z0-9-]{1,24}`, and
  defaults from `WORKSHOP_LEARNER_SUFFIX`.
- Agents are named `asg-<role>-<suffix>`.
- `--delete` removes only agents ending in the caller's suffix.

Dozens of learners can therefore share one subscription.

### Agent categories

`ROLE_DIRS` holds the three coordinator roles and drives readiness.
`WORKSHOP_AGENT_DIRS` holds standalone agents used for teaching. Readiness
must not depend on the latter, or a learner working through Module 1 would
see the coordinator report itself unhealthy.

## Consequences

**Good**

- Agents are visible, versioned, and demonstrable in the portal.
- Prompt agent versus hosted agent becomes a thing you can show, not describe.
- The fast local inner loop is retained.
- Publishing is explicit and reversible, per learner.

**Costs**

- Publishing is a step that can drift from what runs locally. Mitigated by
  `validate_agent_definitions.py`, which prints an instructions hash.
- The server-side namespace is shared. Mitigated by the required suffix.
- Learners must remember to run `--delete`. Facilitators should verify.

## Alternatives rejected

- **Stay ephemeral.** Cheapest, but leaves the portal empty and the repo
  unable to do its job.
- **Publish only, drop the local runtime.** Every prompt edit would need a
  publish round-trip, making the inner loop much slower.
- **Return to persisted Assistants (ADR 0002).** Legacy object model; the
  portal prompts to migrate them. Deleted deliberately.
