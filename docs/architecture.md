# Architecture

`agentic-support-guide` is a customer-demo prototype demonstrating an
Azure AI Foundry three-agent workflow. All data is synthetic. LLM calls
go to a real Azure AI Foundry model deployment.

## Repository layout

```
/agents/                       # Agent definitions (config-only)
  data-analyst/
    agent.md                   # Source of truth for instructions
    manifest.yaml              # Source of truth for runtime metadata
    schemas/                   # Agent-local input/output shapes
  support-recommender/
  validator/

/contracts/v1/                 # Source of truth for inter-agent protocol
  *.schema.json

/services/api/                 # Generic runtime engine (FastAPI)
  app/agents/adapter.py        # LocalManifestAgentAdapter
  app/contracts_registry.py    # Central JSON Schema registry
  app/workflows/coordinator.py # Orchestrator; validates every hop
  app/agents/{data_analyst,support_recommender,validator}/agent.py
      # Thin Python wrappers that delegate to LocalManifestAgentAdapter

/apps/web/                     # React + TS UI
/infra/                        # Terraform for Azure AI Foundry
/docs/                         # Architecture, security, ADRs, GenAIOps
/evals/                        # Synthetic evaluation cases
/scripts/                      # PowerShell + Python demo helpers
```

## Source-of-truth rules

- **`/agents/<id>/agent.md`** — human-readable instructions for the LLM.
  No role-specific prompt text lives in Python.
- **`/agents/<id>/manifest.yaml`** — runtime metadata (which model
  deployment, timeouts, contract references, safety policy).
- **`/contracts/v1/*.schema.json`** — inter-agent protocol. Every
  message that crosses an agent boundary validates against these.
- **`/services/api/`** — the runtime engine. Owns orchestration but not
  agent definitions.

## Independence rules

- Agents (in `/agents`) are configuration-only. No Python
  implementation lives under `/agents`.
- The three Python wrappers (`app/agents/*/agent.py`) do not import each
  other and do not import API internals (`workflows/`, `main`, `models`,
  `plans_store`, `runtime_audit`).
- The coordinator is the only place all three agents meet.
- There is no shared runtime contracts package. `/contracts/v1` holds
  JSON Schemas only. Python's Pydantic types under `services/api/` are
  internal type stubs, not the source of truth.

## Runtime execution

### LocalManifestAgentAdapter

Location: [`services/api/app/agents/adapter.py`](../services/api/app/agents/adapter.py).

For any `agent_id`, the adapter:

1. Reads `/agents/<agent_id>/agent.md` and parses out the body.
2. Reads `/agents/<agent_id>/manifest.yaml` and requires seven keys
   (`id`, `name`, `version`, `runtime`, `contracts`, `handoff`,
   `safety`).
3. Composes a system prompt as `agent.md body + fixed generic envelope`.
   The envelope contains only:
   - "return JSON only",
   - untrusted-data delimiter rule,
   - determination boundaries,
   - "must satisfy the referenced output schema".
4. Calls `LlmProvider.complete_json(...)` with the composed prompt and
   the manifest's `max_output_tokens` / `timeout_seconds` defaults.
5. Parses the response body as JSON and returns the dict. Contract
   validation happens in the coordinator, not here, so this adapter
   stays generic across all agents.

Because the system prompt is derived from `agent.md` at construction
time, editing `agent.md` on disk changes the constructed prompt on next
backend restart — no Python change required.

### The three Python agent classes

`DataAnalystAgent`, `SupportRecommendationAgent`, and `ValidatorAgent`
are now thin wrappers. Each:

- Constructs a `LocalManifestAgentAdapter(agent_id, provider)`.
- Exposes `system_prompt` and `spec_version` properties.
- Wraps the adapter call with a small helper method (`analyze()`,
  `recommend()`, or `validate()`) that formats the user prompt from
  typed context objects and parses the returned payload into internal
  Pydantic types.

The Validator additionally runs deterministic Python checks against the
allowed catalog, required caveats, and required tier framing. The LLM
critique is advisory only and cannot flip a deterministic pass to
failure.

### Coordinator + contracts registry

Location: [`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py)
and [`services/api/app/contracts_registry.py`](../services/api/app/contracts_registry.py).

`AgentCoordinator.run()`:

1. Sanitizes the free-text concern.
2. Calls Data Analyst; if a `provider_missing`/`timeout`/`content_filter`
   error occurs, returns a typed failure envelope with a safe message
   and no recommendation content.
3. Validates the analyst output as a `data-analysis-result` envelope
   against `/contracts/v1/`. If validation fails, returns
   `PROTOCOL_VALIDATION_FAILED`.
4. Calls Support Recommender.
5. Validates the recommender output as `support-recommendation-result`.
6. Runs the Validator Agent (deterministic + optional LLM critique).
7. Validates the validator report as `validation-result`.
8. If the validator failed, re-runs Support Recommender exactly once
   with sanitized repair guidance and re-validates. Data Analyst is
   never re-invoked.
9. Returns a `RecommendationEnvelope` with the final validated
   recommendation and safe trace metadata.

There is no path where `status == "ok"` returns without a validated
recommendation. `status == "ok"` implies contracts registry validation
passed at each step and the Validator deterministic checks passed.

## Trust boundaries

- User concern text is sanitized (`sanitize_free_text`) before wrapping.
- Every untrusted block reaches the LLM inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` delimiters.
- Prior-agent outputs are treated as untrusted data.
- Validator LLM critique text is filtered through `enforce_code()` —
  only strings matching `^[A-Z][A-Z0-9_]{3,59}$` survive.
- Trace metadata exposed to the UI contains only agent name, status,
  provider, model, latency, token estimate, and enumerated
  issue/warning codes.

## Independent deployability

Because `/agents/<id>/` folders are configuration-only and the Python
wrappers do not depend on each other, each agent can move to its own
runtime later:

1. Deploy a small FastAPI (or Foundry-hosted-agent) service per agent.
2. Each service reads its `/agents/<id>/` folder at startup and exposes
   a single endpoint that takes the contract's request envelope and
   returns the response envelope.
3. Update the coordinator's HTTP client to call the remote endpoints
   instead of instantiating the wrapper classes.
4. Nothing about the prompt content or the schemas changes.

## Mapping to Microsoft Agent Framework / Azure AI Foundry

- Each `manifest.yaml` maps to a Microsoft Agent Framework agent
  registration and to a Foundry hosted-agent definition.
- Each `agent.md` maps to the hosted-agent system instructions.
- Each `/contracts/v1/*.schema.json` maps to the hosted workflow's
  strongly-typed message contracts.
- The coordinator maps to a Foundry workflow when the SDK stabilizes.
  Until then, the local Python coordinator is the runtime.

See [`adr/0001-agent-hosting.md`](adr/0001-agent-hosting.md) and
[`adr/0001-foundry-project.md`](adr/0001-foundry-project.md).
