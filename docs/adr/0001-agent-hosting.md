# ADR 0001 - Agent hosting

> **Superseded by [0002-agent-hosting-remote-foundry.md](0002-agent-hosting-remote-foundry.md).**
> This ADR captures the original decision to run each agent locally in
> Python via `LocalManifestAgentAdapter`. That runtime is no longer
> acceptable; the successor ADR explains the move to remote Azure AI
> Foundry Agent Service agents.

Status: Superseded
Date: 2026-01-05

## Context

The prototype needs three collaborating agents backed by Azure AI
Foundry model deployments. Options:

1. Host each agent as a Foundry hosted agent orchestrated by a Foundry
   workflow.
2. Implement each agent as configuration under `/agents/<id>/` and let
   a local Python runtime (`LocalManifestAgentAdapter`) call the Azure
   AI Foundry model deployment directly.

## Decision

**Option 2 for this iteration**, plus scaffolding to move to Option 1
when the SDK stabilizes:

- Agent instructions live in `/agents/<id>/agent.md`.
- Runtime metadata lives in `/agents/<id>/manifest.yaml`.
- Inter-agent protocol lives in `/contracts/v1/*.schema.json` and is
  validated by a central registry in
  [`services/api/app/contracts_registry.py`](../../services/api/app/contracts_registry.py).
- The generic runtime engine is
  `services/api/app/agents/adapter.py` (since removed).
- The three Python classes (`DataAnalystAgent`,
  `SupportRecommendationAgent`, `ValidatorAgent`) are thin wrappers
  that delegate to `LocalManifestAgentAdapter`.

## Rationale

- The current openai + azure-identity SDK path supports keyless chat
  completion against an Azure AI Services account. It does not yet
  offer a stable Foundry-hosted-agent CRUD surface.
- Local orchestration keeps prompts, schema validation, and the repair
  loop entirely inside our test-controllable process.
- Splitting agent definitions from runtime code makes the migration to
  hosted agents mechanical: upload each `agent.md` + `manifest.yaml` +
  contract references into Foundry, then swap
  `LocalManifestAgentAdapter` for a hosted-agent adapter.

## Constraints enforced by the design

- Agents do not contain runtime Python implementation. Anything under
  `/agents/<id>/` is configuration only.
- Agents do not import each other.
- Agents do not import API internals.
- The API does not hardcode role-specific prompt text.
- The contracts registry enforces protocol at every agent hop; the
  coordinator returns a typed `invalid_model_json` /
  `PROTOCOL_VALIDATION_FAILED` result if any hop fails.
- No runtime mock-LLM mode exists. Tests use injected `MockLlmProvider`
  fixtures only.

## Consequences

- The Foundry-hosted-agent path is documented but not implemented.
  `scripts/sync_foundry_agents.py` (since removed)
  is a dry-run validator that verifies manifests and (optionally)
  connects with `DefaultAzureCredential` to prove the sub is reachable.
- Runtime observability includes `spec_version` per agent step, so
  Application Insights queries can bucket outcomes by agent version.
- Editing `/agents/<id>/agent.md` or `manifest.yaml` changes behavior
  without any Python change.

## Migration path

1. When Foundry hosted-agent CRUD is stable, extend
   `sync_foundry_agents.py` to actually create/update hosted agents
   from the same `manifest.yaml` files.
2. Add a `FoundryHostedAgentAdapter` alongside
   `LocalManifestAgentAdapter` that calls the Foundry workflow instead
   of the model deployment directly.
3. Point the three Python wrappers at the new adapter and remove the
   local coordinator branch that runs three sequential HTTP calls,
   replacing it with a single Foundry workflow invocation.
4. Everything under `/agents/` and `/contracts/v1/` stays exactly as
   it is.
