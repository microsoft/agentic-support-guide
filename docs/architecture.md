# Architecture

> See also: [High-level architecture diagram](architecture-diagram.md).

`agentic-support-guide` is a customer-demo prototype demonstrating an
Azure AI Foundry three-agent workflow. All data is synthetic. Every LLM
call runs against the **Azure AI Foundry** project through Microsoft Agent
Framework, with each role composed in-process from `/agents/<id>/agent.md`.
The same definitions are published to Foundry as **prompt agents**, so they
are visible and versioned in the portal. There is no local model call in the
recommendation path.

## The pattern this repo follows

Before diving into files, the target architecture for an agentic
application built this way has seven pieces:

1. **Browser frontend.** A thin UI that collects inputs and renders
   structured outputs. It never talks to a language model directly.
2. **API service.** A backend that owns request handling,
   authentication, input bounds, protocol enforcement, error
   handling, and safe response shaping.
3. **Deterministic orchestration.** Plain application code that
   sequences the agents, enforces timeouts and budgets, runs at most
   one repair pass, and produces a predictable failure taxonomy. This
   is not a language-model agent — it is regular code the tests can
   drive with a fake client.
4. **Remote agents.** Each specialized reasoning role is composed from
   `/agents/<id>/agent.md` — instructions plus a bound model deployment —
   and published to Foundry as a versioned prompt agent.
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
  support-explainer/           # Standalone workshop agent, not a coordinator role

/contracts/v1/                 # Source of truth for inter-agent protocol
  *.schema.json

/.foundry/                     # Local, gitignored Foundry scratch state

/services/api/                 # Orchestration + FastAPI (no direct model calls)
  app/foundry_agents/          # ONLY place that imports the Foundry SDK
    maf_client.py              #   the only Agent Framework SDK import
    maf_runtime.py             #   MafAgentRuntime (role -> Agent per call)
    role_definitions.py        #   roles from agent.md + deployment env vars
    error_mapping.py           #   provider errors -> app taxonomy
    prompt_envelope.py         #   compose_instructions(), shared with the publish scripts
    errors.py                  #   typed provider errors
  app/agents/{data_analyst,support_recommender,validator}/agent.py
                               # Role wrappers that call the remote adapter
  app/workflows/               # Agent Framework graph, executors, coordinator
  app/contracts_registry.py    # Central JSON Schema registry

/apps/web/                     # React + TS UI
/infra/                        # Terraform for Azure AI Foundry
/docs/                         # Architecture, security, ADRs, GenAIOps
/evals/                        # Synthetic evaluation cases
/scripts/                      # validate_agent_definitions.py, populate-env.ps1, ...
```

## Source-of-truth rules

- **`/agents/<id>/agent.md`** — instructions the remote Foundry agent
  sees. No role-specific prompt text lives in Python.
- **`/agents/<id>/manifest.yaml`** — runtime metadata + the `foundry:`
  binding block (agent name, model deployment env var, temperature,
  response format).
- **`/contracts/v1/*.schema.json`** — inter-agent protocol. Every
  message that crosses an agent boundary validates against these.
- **`/services/api/`** — the orchestration engine and Foundry adapter.

## Independence rules

- Agents (in `/agents`) are configuration-only. No Python
  implementation lives under `/agents`.
- The three Python wrappers (`app/agents/*/agent.py`) do not import
  each other and do not import API internals (`workflows/`, `main`,
  `models`, `plans_store`, `runtime_audit`).
- The coordinator is the only place all three agents meet.
- No file outside `app/foundry_agents/maf_client.py` may import
  `azure.ai.agents`, `AzureOpenAI`, `openai.`, or reference
  `chat.completions`. This is asserted by
  `tests/test_no_persisted_agents.py`, which also keeps publishing symbols
  (`to_prompt_agent`, `create_version`) out of the request path - publishing
  is a GenAIOps step, allowlisted to `scripts/publish_prompt_agents.py`, and
  must never be triggered by a web request.

## Runtime execution

### MafAgentRuntime

Location:
[`services/api/app/foundry_agents/maf_runtime.py`](../services/api/app/foundry_agents/maf_runtime.py).

For a given role name (e.g. `data-analyst-agent`) and user message, the
adapter:

1. Looks up the role in `self._roles`, loaded from `agents/<id>/agent.md` and
   its `manifest.yaml` at startup. Nothing is resolved against Foundry.
2. Composes the instructions and calls `FoundryResponsesClientFactory`, which
   creates a single-turn Responses call with `store=False` and a
   `response_format` bound to the role's Pydantic contract, then returns the
   raw text.
3. Maps SDK-level failures into typed `FoundryProviderError` subclasses
   (`ConfigurationError`, `AuthError`, `ThrottledError`,
   `ContentFilterError`, `FoundryTimeoutError`, `RequiresActionError`,
   `FoundryRunError`).

`scripts/validate_agent_definitions.py --check-connectivity` verifies the
definitions load and the configured project answers, without creating
anything.

There is no local fallback: if the adapter cannot invoke the remote
agent, it raises. The coordinator translates that into a typed API
error.

### The three Python role classes

`DataAnalystAgent`, `SupportRecommendationAgent`, and `ValidatorAgent`
are now thin role wrappers. Each:

- Holds a reference to a `MafAgentRuntime`.
- Builds the role-specific user message (untrusted-data delimiters,
     concern text, prior-agent output as an untrusted block).
- Calls `adapter.invoke(role=..., user_message=...)`.
- Parses the returned text as JSON and validates it with the internal
  Pydantic type for that role.

The Validator additionally runs deterministic Python checks against the
allowed catalog, required caveats, and required tier framing. The LLM
critique step delegates to the remote validator agent and is advisory
only — it cannot flip a deterministic pass to failure.

### Coordinator + contracts registry

Location:
[`services/api/app/workflows/`](../services/api/app/workflows/)
and
[`services/api/app/contracts_registry.py`](../services/api/app/contracts_registry.py).

`AgentCoordinator.run()` does three things: it builds a `RunState`, builds a
fresh Agent Framework workflow with
`build_plan_workflow(...)`, and runs it under the wall-clock budget:

```python
events = await asyncio.wait_for(
    built.workflow.run(PlanState(concern=concern)),
    timeout=max(0.0, state.deadline - time.monotonic()),
)
```

It catches `StepFailed` and `TimeoutError` and returns a `CoordinatorResult`
carrying a typed failure envelope. A `Workflow` instance rejects concurrent
runs, so one is built per request.

The sequence itself lives in the graph, not in the coordinator.
[`graph.py`](../services/api/app/workflows/graph.py) wires six executors with
six edges:

```
RetrieveEvidence -> Analyse -> Recommend -> Validate -> Finalise
                                   ^            |
                                   +-- repair --+--> Refuse
```

- Each hop is validated against `/contracts/v1/` by `PlanRun.check_handoff`
  before the next executor sees it. A failure raises `StepFailed` with
  `PROTOCOL_VALIDATION_FAILED`.
- `Validate` runs the deterministic checks plus an advisory LLM critique. The
  critique cannot flip a deterministic verdict.
- The repair bound is the `needs_repair` edge condition in
  [`plan.py`](../services/api/app/workflows/plan.py), not a loop:
  `MAX_RECOMMENDER_ATTEMPTS` is 2. When it is exhausted the
  `repair_exhausted` edge routes to `Refuse`, which returns
  `VALIDATION_FAILED_AFTER_REPAIR`. `RetrieveEvidence` and `Analyse` are never
  re-run.

There is no path where `status == "ok"` returns without a validated
recommendation.

## The coordinator is not an agent

The coordinator is deterministic Python that builds the graph and enforces the
budget. It is not a fourth agent, does not talk to a base model, and does not
appear as a Foundry agent. This is intentional — it keeps the sequence, the
protocol validation, and the failure taxonomy in code the test suite
can exercise with a fake client.

## Trust boundaries

- User concern text is length-bounded before wrapping.
- Every untrusted block reaches the remote agent inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` delimiters.
- Prior-agent outputs are treated as untrusted data.
- Validator LLM critique text is filtered through `enforce_code()` —
  only strings matching `^[A-Z][A-Z0-9_]{3,59}$` survive.
- Trace metadata exposed to the UI contains only agent name, status,
  provider (`azure_foundry_responses` for the model steps, the retriever's
  own name — `fixture` or `foundry_iq` — for evidence retrieval), the served
  model, latency, token estimate, citation count, and enumerated
  issue/warning codes. No prompts or completions are exposed.

## Deployment / provisioning flow

The DevOps and GenAIOps halves are separate: Terraform provisions
infrastructure and never creates an agent. Publishing agents is a distinct,
explicit step run by `scripts/publish_prompt_agents.py` and
`scripts/publish_hosted_agent.py`, and the running application does not depend
on it.

1. `terraform apply` in `/infra` provisions the Foundry project and
   model deployments.
2. `scripts/populate-env.ps1` copies the outputs into
   `services/api/.env` (including `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
   and the per-role `FOUNDRY_MODEL_DEPLOYMENT_*` names).
3. Start the backend with `--env-file .env`. The app reads its
   configuration from the process environment and does not load `.env`
   implicitly.
4. `/api/health/details` reports `foundry_project_configured`,
   `agent_definitions_valid`, `model_deployments_configured`, and
   `service_side_remote_workflow_active`.

Editing `/agents/<id>/agent.md` takes effect on the next request, because
the instructions are composed per call. Rolling back is a revert commit,
not a redeployment. `python scripts/validate_agent_definitions.py`
validates the definitions offline and prints an `instructions_hash` per
role so you can confirm a change landed.

See [`adr/0006-published-prompt-agents.md`](adr/0006-published-prompt-agents.md) and
[`adr/0001-foundry-project.md`](adr/0001-foundry-project.md).

## Dealer group isolation, evidence retrieval, and human review

Three concerns overlay the base workflow. They are all first-class in
the contracts and enforced in code, not in prompts.

### Dealer group isolation (`dealer_group_id`)

Every request carries a `dealer_group_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`. It is required by:

- `SupportPlanRequest` at the HTTP boundary.
- Every JSON Schema in `/contracts/v1/` (request, result, citation).
- `DataAnalystOutput`, `SupportRecommendationDraft`, `ValidatorReport`,
  and `Citation` on the Python side.
- The runtime audit and telemetry rows.

The Validator Agent raises `DRAFT_DEALER_GROUP_MISMATCH` and
`CROSS_DEALER_GROUP_CITATION` deterministically if anything drifts. See
[`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md).

### Evidence retrieval

The coordinator retrieves evidence **before** invoking any agent:

```
services/api/app/evidence/
  retrieval.py    # EvidenceRetriever Protocol (stable interface)
  fixtures.py     # FixtureEvidenceRetriever (synthetic per-dealer group)
```

The bundle is passed to the Support Recommendation Agent, which
attaches citations by ID. The Validator Agent checks citation
integrity (`MISSING_CITATIONS`, `UNKNOWN_CITATION_ID`,
`CROSS_DEALER_GROUP_CITATION`). See
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
`review_transition` events with `correlation_id`, `dealer_group_id`, old
state, new state, and reviewer identifier. No prompt or completion text
is stored.

### Correlation IDs

The coordinator generates a `correlation_id` per request and stamps it
on every envelope, every audit row, and every review-transition record.
It is deliberately **not** on individual trace steps. See
[`observability.md`](observability.md).

## Related documents

- [`agents-vs-prompts.md`](agents-vs-prompts.md) - why this is a
  multi-agent workflow instead of one bigger prompt.
- [`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md)
- [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
- [`security-and-privacy.md`](security-and-privacy.md)
- [`observability.md`](observability.md)

