# Agents

This folder is the **source of truth for agent configuration**, and it is
what the runtime actually loads. It is intentionally protocol- and
configuration-only: no Python implementation lives here.

Agents are **ephemeral at runtime**. At startup the backend composes each
role's instructions from `agent.md` (body plus the behavioural rules in its
YAML frontmatter) and caches them for the life of the process, then runs each
call against the Foundry project's Responses API via
Microsoft Agent Framework. The runtime never calls a published copy, so the
version that runs is exactly the version on your branch.

Publishing is a separate GenAIOps step: `scripts/publish_prompt_agents.py`
pushes these same definitions to Foundry as versioned **prompt agents** so
they are visible in the portal. See
[ADR 0006](../docs/adr/0006-published-prompt-agents.md), which supersedes
[ADR 0005](../docs/adr/0005-agent-framework-ephemeral-agents.md).

The loader is
[`services/api/app/foundry_agents/role_definitions.py`](../services/api/app/foundry_agents/role_definitions.py),
which composes instructions through
[`prompt_envelope.py`](../services/api/app/foundry_agents/prompt_envelope.py).

## Layout

```
/agents/
  <agent-name>/
    agent.md          # human-readable instructions (source of truth)
    manifest.yaml     # runtime metadata (spec version, model, contracts)
    schemas/
      input.schema.json
      output.schema.json
```

- `agent.md` is the source of truth for the human-readable instructions
  the LLM receives.
- `manifest.yaml` is the source of truth for **runtime metadata**:
  which model deployment to call, the schema contract versions, the
  handoff targets, and safety policy references.
- `schemas/input.schema.json` and `schemas/output.schema.json` describe
  the **agent-local** payloads - exactly what the model is asked to emit.
  They deliberately omit fields the coordinator injects from trusted
  context (for example `dealer_group_id`). Cross-agent envelope messages,
  which do carry those fields, live in
  [`/contracts/v1/`](../contracts/v1/).
- Agent behavior is tested from the FastAPI suite in
  [`services/api/tests`](../services/api/tests); there are no
  agent-scoped test folders.

## Source-of-truth rules

- `agent.md` is authoritative for prompt content. Python must not
  duplicate role-specific prompt text.
- `manifest.yaml` is authoritative for runtime metadata: model
  deployment name, temperature, `max_output_tokens`, output-format hints,
  contract versions. Request timeouts are not per agent — one wall-clock
  budget governs the whole orchestration.
- `/contracts/v1/*.schema.json` is authoritative for **inter-agent**
  messages. Compatibility rules are documented in
  [`/contracts/README.md`](../contracts/README.md).

## Editing an agent

1. Edit `agent.md`. Behavioural rules (`constraints`, `safety_rules`,
   `grounding_rules`) live in the YAML frontmatter and **are** sent to the
   model - dropping them yields plausible but off-contract output.
2. Run `python scripts/validate_agent_definitions.py`. It validates the
   manifest, contract references, and frontmatter, and prints an
   `instructions_hash` per role so you can see the change took effect.
3. Restart the backend. There is no deploy or sync step.

CI runs the same validation, plus `scripts/run_evals.py --offline`, on
every pull request.
