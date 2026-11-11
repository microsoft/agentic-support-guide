# Agents

This folder is the **source of truth for agent configuration**, and it is
what the runtime actually loads. It is intentionally protocol- and
configuration-only: no code lives here. Both tracks, Python and .NET, load
these same files.

Agents are **ephemeral at runtime**. At startup the backend composes each
role's instructions from `agent.md` (body plus the behavioural rules in its
YAML frontmatter) and caches them for the life of the process, then runs each
call against the Foundry project's Responses API via
Microsoft Agent Framework. The runtime never calls a published copy, so the
version that runs is exactly the version on your branch.

Publishing is a separate GenAIOps step: `python/scripts/publish_prompt_agents.py`
or `dotnet/scripts/publish_prompt_agents.cs` pushes these same definitions to
Foundry as versioned **prompt agents** so they are visible in the portal. See
[ADR 0006](../docs/adr/0006-published-prompt-agents.md), which supersedes
[ADR 0005](../docs/adr/0005-agent-framework-ephemeral-agents.md).

The Python loader is
[`python/services/api/app/foundry_agents/role_definitions.py`](../python/services/api/app/foundry_agents/role_definitions.py),
which composes instructions through
[`prompt_envelope.py`](../python/services/api/app/foundry_agents/prompt_envelope.py).
The .NET loader is
[`RoleDefinitions.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/RoleDefinitions.cs),
which composes them through
[`PromptEnvelope.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/PromptEnvelope.cs);
the .NET build copies this folder next to the app, which reads it from there.
The .NET conformance tests check that it composes the three coordinator
roles' instructions byte for byte as the Python track does.

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
  context (for example `dealer_group_id`). The manifest's `contracts`
  block points at them.
- Agent behavior is tested from each track's API test suite —
  [`python/services/api/tests`](../python/services/api/tests) and
  [`dotnet/services/api/AgenticSupportGuide.Api.Tests`](../dotnet/services/api/AgenticSupportGuide.Api.Tests);
  there are no agent-scoped test folders.

## Source-of-truth rules

- `agent.md` is authoritative for prompt content. Application code, in
  either track, must not duplicate role-specific prompt text.
- `manifest.yaml` is authoritative for runtime metadata: model
  deployment name, temperature, `max_output_tokens`, output-format hints,
  contract versions. There are no per-agent timeouts.

## Editing an agent

1. Edit `agent.md`. Behavioural rules (`constraints`, `safety_rules`,
   `grounding_rules`) live in the YAML frontmatter and **are** sent to the
   model - dropping them yields plausible but off-contract output.
2. Run `python python/scripts/validate_agent_definitions.py` or
   `dotnet run dotnet/scripts/validate_agent_definitions.cs`. It validates
   the manifest, contract references, and frontmatter, and prints an
   `instructions_hash` per role so you can see the change took effect.
3. Restart the backend. There is no deploy or sync step. In the .NET track
   the restart must also rebuild, because the build is what copies this
   folder next to the app; `.\dotnet\scripts\run-backend.ps1` rebuilds when
   it starts.

Each track's CI runs the same validation, plus its test suite, on every pull
request.
