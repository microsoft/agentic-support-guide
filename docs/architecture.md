# Architecture

> See also: [High-level architecture diagram](architecture-diagram.md).

`agentic-support-guide` is a customer-demo prototype demonstrating an
Azure AI Foundry three-agent workflow. All data is synthetic. Every LLM
call is a run against a remote **Azure AI Foundry Agent Service**
assistant. There is no local model call in the recommendation path.

## The pattern this repo follows

Before diving into files, the target architecture for an agentic
application built this way has seven pieces:

1. **Browser frontend.** A thin UI that collects inputs and renders
   structured outputs. It never talks to a language model directly.
2. **API service.** A backend that owns request handling,
   authentication, input sanitization, protocol enforcement, error
   handling, and safe response shaping.
3. **Deterministic orchestration.** Plain application code that
   sequences the agents, enforces timeouts and budgets, runs at most
   one repair pass, and produces a predictable failure taxonomy. This
   is not a language-model agent — it is regular code the tests can
   drive with a fake client.
4. **Remote agents.** Each specialized reasoning role runs as a
   separate assistant on Azure AI Foundry Agent Service, configured by
   instructions and a bound model deployment.
5. **Protocol validation.** Every inter-agent message validates
   against a versioned JSON Schema before it is used. Invalid
   messages become typed failures, never surfaced content.
6. **Synthetic data boundary.** The application reads only in-memory
   synthetic data. There is no external data source in the demo.
7. **Observability boundary.** Only metadata (agent name, status,
   latency, coarse error code) leaves the process. Prompts,
   completions, and raw user text are never emitted.

This is the pattern to keep in mind while reading the rest of this
document.

## Repository layout

```
/agents/                       # Agent definitions (config-only)
  data-analyst/
    agent.md                   # Source of truth for instructions
    manifest.yaml              # Source of truth for runtime metadata
                               #  incl. `foundry:` binding block
    schemas/                   # Agent-local input/output shapes
  support-recommender/
  validator/

/contracts/v1/                 # Source of truth for inter-agent protocol
  *.schema.json

/.foundry/                     # Local, environment-specific Foundry bindings
  agent-bindings.example.json  # Committed example (not real IDs)
  agent-bindings.local.json    # Gitignored, produced by sync script

/services/api/                 # Orchestration + FastAPI (no direct model calls)
  app/foundry_agents/          # ONLY place that imports azure-ai-agents
    sdk_client.py              #   thin wrapper around AgentsClient
    adapter.py                 #   FoundryRemoteAgentAdapter (role -> asst)
    bindings.py                #   read/write .foundry/agent-bindings.local.json
    prompt_envelope.py         #   compose_instructions() shared with sync script
    errors.py                  #   typed provider errors
  app/agents/{data_analyst,support_recommender,validator}/agent.py
                               # Role wrappers that call the remote adapter
  app/workflows/coordinator.py # Deterministic orchestrator; validates every hop
  app/contracts_registry.py    # Central JSON Schema registry

/apps/web/                     # React + TS UI
/infra/                        # Terraform for Azure AI Foundry
/docs/                         # Architecture, security, ADRs, GenAIOps
/evals/                        # Synthetic evaluation cases
/scripts/                      # sync_foundry_agents.py, populate-env.ps1, ...
```

## Source-of-truth rules

- **`/agents/<id>/agent.md`** — instructions the remote Foundry agent
  sees. No role-specific prompt text lives in Python.
- **`/agents/<id>/manifest.yaml`** — runtime metadata + the `foundry:`
  binding block (agent name, model deployment env var, temperature,
  response format).
- **`/contracts/v1/*.schema.json`** — inter-agent protocol. Every
  message that crosses an agent boundary validates against these.
- **`/.foundry/agent-bindings.local.json`** — the role → remote
  assistant ID map. Environment-specific and gitignored. Produced by
  `scripts/sync_foundry_agents.py --apply`.
- **`/services/api/`** — the orchestration engine and Foundry adapter.

## Independence rules

- Agents (in `/agents`) are configuration-only. No Python
  implementation lives under `/agents`.
- The three Python wrappers (`app/agents/*/agent.py`) do not import
  each other and do not import API internals (`workflows/`, `main`,
  `models`, `plans_store`, `runtime_audit`).
- The coordinator is the only place all three agents meet.
- No file outside `app/foundry_agents/sdk_client.py` may import
  `azure.ai.agents`, `AzureOpenAI`, `openai.`, or reference
  `chat.completions`. This is asserted by
  `tests/test_agents_config.py::test_no_direct_model_calls_outside_sdk_client`.

## Runtime execution

### FoundryRemoteAgentAdapter

Location:
[`services/api/app/foundry_agents/adapter.py`](../services/api/app/foundry_agents/adapter.py).

For a given role name (e.g. `data-analyst-agent`) and user message, the
adapter:

1. Looks up the role in the loaded bindings map.
2. Refuses to invoke if the binding was produced against a different
   Foundry project endpoint (`project_endpoint_hash` mismatch) — the
   operator must re-run the sync script with `--rebind`.
3. Delegates to `FoundryAgentClient.run_agent(...)`, which creates a
   thread, adds the user message, creates a run bound to the
   assistant, polls until a terminal status, reads the last assistant
   message, and returns the raw text.
4. Maps SDK-level failures into typed `FoundryProviderError` subclasses
   (`ConfigurationError`, `AuthError`, `ThrottledError`,
   `ContentFilterError`, `FoundryTimeoutError`, `RequiresActionError`,
   `FoundryRunError`).

There is no local fallback: if the adapter cannot invoke the remote
agent, it raises. The coordinator translates that into a typed API
error.

### The three Python role classes

`DataAnalystAgent`, `SupportRecommendationAgent`, and `ValidatorAgent`
are now thin role wrappers. Each:

- Holds a reference to a `FoundryRemoteAgentAdapter`.
- Builds the role-specific user message (untrusted-data delimiters,
  sanitized concern text, prior-agent output as an untrusted block).
- Calls `adapter.invoke(role=..., user_message=...)`.
- Parses the returned text as JSON and validates it with the internal
  Pydantic type for that role.

The Validator additionally runs deterministic Python checks against the
allowed catalog, required caveats, and required tier framing. The LLM
critique step delegates to the remote validator agent and is advisory
only — it cannot flip a deterministic pass to failure.

### Coordinator + contracts registry

Location:
[`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py)
and
[`services/api/app/contracts_registry.py`](../services/api/app/contracts_registry.py).

`AgentCoordinator.run()`:

1. Sanitizes the free-text concern.
2. Calls Data Analyst; if any typed provider error occurs, returns a
   typed failure envelope with a safe message and no recommendation.
3. Validates the analyst output as a `data-analysis-result` envelope
   against `/contracts/v1/`. If validation fails, returns
   `PROTOCOL_VALIDATION_FAILED`.
4. Calls Support Recommender.
5. Validates the recommender output as `support-recommendation-result`.
6. Runs the Validator Agent (deterministic + advisory LLM critique).
7. Validates the validator report as `validation-result`.
8. If the validator failed, re-runs Support Recommender exactly once
   with sanitized repair guidance and re-validates. Data Analyst is
   never re-invoked.
9. Returns a `RecommendationEnvelope` with the final validated
   recommendation and safe trace metadata.

There is no path where `status == "ok"` returns without a validated
recommendation.

## The coordinator is not an agent

The coordinator is deterministic Python that ordered the calls, ran the
protocol registry, and enforced the one-shot repair loop. It is not a
fourth agent, does not talk to a base model, and does not appear as a
Foundry agent. This is intentional — it keeps the sequence, the
protocol validation, and the failure taxonomy in code the test suite
can exercise with a fake client.

## Trust boundaries

- User concern text is sanitized (`sanitize_free_text`) before wrapping.
- Every untrusted block reaches the remote agent inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` delimiters.
- Prior-agent outputs are treated as untrusted data.
- Validator LLM critique text is filtered through `enforce_code()` —
  only strings matching `^[A-Z][A-Z0-9_]{3,59}$` survive.
- Trace metadata exposed to the UI contains only agent name, status,
  provider (always `azure_foundry_agents`), latency, and enumerated
  issue/warning codes. No prompts, completions, thread IDs, run IDs,
  or assistant IDs are exposed.

## Deployment / provisioning flow

1. `terraform apply` in `/infra` provisions the Foundry project and
   model deployments.
2. `scripts/populate-env.ps1` copies the outputs into
   `services/api/.env` (including `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
   and the per-role `FOUNDRY_MODEL_DEPLOYMENT_*` names).
3. `python scripts/sync_foundry_agents.py --apply` reads
   `/agents/<id>/{agent.md, manifest.yaml}`, creates or updates one
   remote assistant per role, and writes
   `.foundry/agent-bindings.local.json` with the assistant IDs and
   an `instructions_hash` for drift detection.
4. Restart the backend. `/api/health/details` reports
   `foundry_project_configured`, `foundry_agents_bound`, and
   `service_side_remote_workflow_active`.

Editing `/agents/<id>/agent.md` or `manifest.yaml` and re-running
`--apply` updates the remote agent in place. The instructions hash
guards against silent drift.

See [`adr/0002-agent-hosting-remote-foundry.md`](adr/0002-agent-hosting-remote-foundry.md) and
[`adr/0001-foundry-project.md`](adr/0001-foundry-project.md).

## District isolation, evidence retrieval, and human review

Three concerns overlay the base workflow. They are all first-class in
the contracts and enforced in code, not in prompts.

### District isolation (`district_id`)

Every request carries a `district_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`. It is required by:

- `SupportPlanRequest` at the HTTP boundary.
- Every JSON Schema in `/contracts/v1/` (request, result, citation).
- `DataAnalystOutput`, `SupportRecommendationDraft`, `ValidatorReport`,
  and `Citation` on the Python side.
- The runtime audit and telemetry rows.

The Validator Agent raises `DRAFT_DISTRICT_MISMATCH` and
`CROSS_DISTRICT_CITATION` deterministically if anything drifts. In the
target production topology, each district maps to its own Fabric
workspace and lakehouse (see
[`adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)
and [`foundry-fabric-deep-dive.md`](foundry-fabric-deep-dive.md)).

### Evidence retrieval

The coordinator retrieves evidence **before** invoking any agent:

```
services/api/app/evidence/
  retrieval.py    # EvidenceRetriever Protocol (stable interface)
  fixtures.py     # FixtureEvidenceRetriever (synthetic per-district)
```

The bundle is passed to the Support Recommendation Agent, which
attaches citations by ID. The Validator Agent checks citation
integrity (`MISSING_CITATIONS`, `UNKNOWN_CITATION_ID`,
`CROSS_DISTRICT_CITATION`). See
[`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md).

### Human review lifecycle

Every recommendation is created in `human_review_state = pending_review`.
Allowed transitions live in
[`services/api/app/human_review.py`](../services/api/app/human_review.py):

```
draft            -> pending_review
pending_review   -> approved | rejected
rejected         -> pending_review
approved         (terminal)
```

Transitions go through `POST /api/supports/plans/{plan_id}/review`
and are recorded in the runtime audit log as
`review_transition` events with `correlation_id`, `district_id`, old
state, new state, and reviewer identifier. No prompt or completion text
is stored.

### Correlation IDs

The coordinator generates a `correlation_id` per request and stamps it
on every envelope, every audit row, every trace step, and every
review-transition record. See
[`observability.md`](observability.md).

## The Support Recommendation Agent

The recommender is referred to as the **Support Recommendation Agent**
throughout the code, UI, and current documentation. Earlier internal
notes may have called it "Interventionist", "Interventionalist", or
"Instructional Expert"; those labels are historical only and are not
used as identifiers today.

## Related documents

- [`agents-vs-prompts.md`](agents-vs-prompts.md) - why this is a
  multi-agent workflow instead of one bigger prompt.
- [`foundry-fabric-deep-dive.md`](foundry-fabric-deep-dive.md) -
  how Foundry and Fabric fit together in the target topology.
- [`adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)
- [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
- [`security-and-privacy.md`](security-and-privacy.md)
- [`observability.md`](observability.md)
