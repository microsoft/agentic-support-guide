# ADR 0005 — Microsoft Agent Framework with ephemeral Foundry agents

Status: Superseded by [ADR 0006 — published prompt agents](0006-published-prompt-agents.md)
Date: 2026-09-03
Supersedes: [ADR 0002 — agent hosting on remote Foundry](0002-agent-hosting-remote-foundry.md)

> **Superseded.** The "ephemeral agents" decision below removed the portal
> popup, but it also removed the agents from the Foundry portal entirely.
> Portal visibility is a primary requirement for this repo — it is how the
> agent model is demonstrated. ADR 0006 keeps the Agent Framework runtime
> and adds a publish step so the same definitions appear as prompt agents.

## Context

ADR 0002 hosted each role as a **persisted assistant** in Azure AI Foundry,
created by a sync script and referenced by `asst_*` IDs in a local bindings
file. Three problems surfaced in practice:

1. **The framework was implied, not used.** The repo described a "Microsoft
   Agent Framework–style" pattern while hand-rolling the orchestration
   against the Assistants SDK.
2. **The Foundry portal flagged the agents for migration.** The current
   portal experience does not render Assistants-model objects and prompts
   "Update your agents". Accepting that prompt copies agents to new IDs and
   orphans the bindings file.
3. **Persisted agents are a shared namespace.** This repo is used by dozens
   of learners, frequently in the same subscription. Server-side agent names
   are one more thing that can collide, and one more thing to clean up.

## Decision

Use the **Microsoft Agent Framework** (`agent-framework-foundry`) with
`FoundryChatClient`, which calls the Foundry project's **Responses API**.
This produces *ephemeral* agents: the definition is assembled in-process from
`/agents/<id>/agent.md` on every call, and nothing is persisted server-side.

- Each role is an `agent_framework.Agent` created per call.
- `FoundryChatOptions` carries `response_format` (a Pydantic contract model),
  `store=False`, and the per-role temperature.
- No MAF session or `conversation_id` is reused across roles or across the
  repair pass, preserving the isolation boundary between agents.
- The deterministic Python coordinator is unchanged in role: it still owns
  ordering, contract validation, budgets, district scoping, and the one-shot
  repair loop. It is not an agent and does not call a model.

## Consequences

**Gained**
- The actual framework, not a lookalike pattern.
- No persisted agents, so no portal migration prompt and no `asst_*`
  namespace to collide on or clean up.
- Agent definitions version with the application in git. Rolling back a
  prompt is a revert, not a deployment.
- A cleaner DevOps/GenAIOps split: Terraform provisions infrastructure and
  never creates agents; there is no agent deploy step at all.

**Lost / traded**
- No server-side agent versioning or Foundry-side agent listing. Version
  history lives in git, and the composed `instructions_hash` is surfaced by
  `scripts/validate_agent_definitions.py`.
- The runtime is now async end to end (`Agent.run` is a coroutine), which
  changed the coordinator, the three role wrappers, and the recommendation
  endpoint.
- Provider errors arrive wrapped in a generic `ChatClientException`, so
  classification unwraps `__cause__`. See
  `services/api/app/foundry_agents/error_mapping.py`.

## Guardrails

- `tests/test_no_persisted_agents.py` fails if `FoundryAgent`,
  `RawFoundryAgent`, or `to_prompt_agent` is imported, or if agent CRUD calls
  reappear. Those would silently restore persisted agents.
- `tests/test_provider_vocabulary.py` greps YAML, TypeScript, PowerShell, and
  Markdown for retired vocabulary, because the provider identifier cannot be
  imported by those languages.
- `store=False` is set on every call and asserted by the test double.
