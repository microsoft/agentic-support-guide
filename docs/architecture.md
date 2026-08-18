# Architecture

`agentic-support-guide` is a local-first prototype demonstrating an
Azure AI Foundry project-oriented development pattern for education-style
analytics and learner support planning. All data is synthetic. Real LLM
calls flow through Azure AI Foundry model deployments.

## High-level shape

```
apps/web (Vite + React + TS)
   |
   |  HTTP /api/*  (Vite dev proxy -> 127.0.0.1:8000)
   v
services/api (FastAPI, Python 3.12)
   |
   |  three collaborating agents via typed contracts
   v
Azure AI Foundry project + model deployment (Azure AI Services account)
```

## Modules

Backend capability modules under `services/api/app`:

- `learners`, `assessments`, `behavior`, `dashboard`, `supports`, `audit` -
  synthetic-data query and aggregation.
- `mock_data`, `repositories` - deterministic seeded fixtures.
- `plans_store`, `runtime_audit` - in-memory stores (reset on restart).
- `llm` - `LlmProvider` interface plus `AzureFoundryLlmProvider` and
  `MockLlmProvider`.
- `agents/shared/contracts.py` - immutable Pydantic contracts exchanged
  between agents. Imports nothing from agent implementations.
- `agents/shared/sanitization.py` - prompt-injection defenses and
  untrusted-data delimiters.
- `agents/data_analyst`, `agents/support_recommender`, `agents/validator` -
  three implemented agents. Each has a narrow typed interface and knows
  nothing about the others.
- `workflows/coordinator.py` - `AgentCoordinator`, the only place that
  sequences agents and passes typed messages between them.
- `telemetry.py` - metadata-only telemetry facade.

## The three implemented agents

- **Data Analyst Agent** produces a `DataAnalystOutput` (evidence bullets,
  detected need, missing-data flags, analysis confidence). No
  intervention suggestions.
- **Support Recommendation Agent** consumes the analyst output as
  untrusted data and produces a `SupportRecommendationDraft` (support
  tier, frequency, grouping, chosen resource ids, SMART goal ids,
  strategy ids, next steps, progress monitoring, caveats). Only chooses
  from the allowed catalog supplied in the request context.
- **Validator Agent** runs deterministic pass/fail checks against the
  allowed catalog, schema, and required-caveat rules. Optional LLM
  critique adds advisory warnings; it never flips a deterministic pass
  to a failure.

## Shared contracts as a bounded context

`agents/shared/contracts.py` is intentionally a leaf module. It defines
`AnalysisSummary`, `DataAnalystOutput`, `SupportRecommendationDraft`,
`ValidatorReport`, `ResourceRef`, and `AgentEnvelope`. Every message
carries `contract_version`. The file could later be extracted into a
versioned shared library or schema registry with no runtime change to
agents or the coordinator.

## The coordinator

`AgentCoordinator.run`:

1. Sanitizes free-text concern input.
2. Calls Data Analyst.
3. Calls Support Recommender with the analyst output as delimited
   untrusted data.
4. Runs deterministic validation via the Validator Agent (optionally with
   LLM critique).
5. If validation fails, re-runs the recommender **once** with sanitized
   repair guidance, then re-validates deterministically.
6. Returns either a validated `Recommendation` and a three-step agent
   trace, or a typed failure envelope with safe issue/warning codes.

There is no recursion and no additional repair loop. Data Analyst is
never re-run during repair.

## Trust and message flow

- User concern text is sanitized and wrapped in `<<<UNTRUSTED_DATA>>>`
  blocks. Prompts instruct the model to treat blocks as data only.
- Prior-agent outputs are also carried as untrusted data blocks.
- Trace metadata surfaced to the UI contains only agent name, status,
  provider, model, latency, token estimate, and enumerated
  issue/warning codes. Prompts, completions, and raw validator critique
  never leave the backend.

## Independent deployability

`apps/web` and `services/api` are independently runnable and are wired
only through HTTP. The three agent modules are also independently
testable and independently deployable in the future. See
[future-azure-architecture.md](./future-azure-architecture.md) for the
migration path.

## Mapping to Microsoft Agent Framework / Azure AI Foundry concepts

- `LlmProvider` maps to a Microsoft Agent Framework chat/model client
  bound to an Azure AI Foundry deployment.
- Each agent maps to a Microsoft Agent Framework agent with a single
  responsibility, structured JSON output, and a strict input contract.
- `AgentCoordinator` maps to a Microsoft Agent Framework workflow or
  orchestration graph. Because the graph is small and the prototype uses
  keyless Azure OpenAI calls, the coordinator is implemented as an
  explicit Python class today. See
  [`adr/0001-agent-hosting.md`](./adr/0001-agent-hosting.md) and
  [`adr/0001-foundry-project.md`](./adr/0001-foundry-project.md) for the
  decision records.
- The Foundry project scope (`azurerm_cognitive_account_project`) is the
  organizational unit for the model deployment, RBAC, and future hosted
  agents. `AZURE_AI_FOUNDRY_PROJECT_NAME` is exposed to the backend for
  observability today; chat completion routing uses the AI Services
  endpoint because that is what the current openai + azure-identity SDK
  supports cleanly.
