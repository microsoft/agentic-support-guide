# Architecture

> See also: [High-level architecture diagram](architecture-diagram.md).

`agentic-support-guide` is a customer-demo prototype demonstrating an
Microsoft Foundry three-agent workflow. All data is synthetic. Every LLM
call runs against the **Microsoft Foundry** project through Microsoft Agent
Framework, with each role composed in-process from `/agents/<id>/agent.md`.
The same definitions are published to Foundry as **prompt agents**, so they
are visible and versioned in the portal. There is no local model call in the
recommendation path.

The application is implemented twice, in a Python track and a .NET track that
behave the same; see [Choose a track](../workshop/README.md#choose-a-track).
This page names both tracks' files. Where Agent Framework for Python and
Agent Framework for .NET genuinely behave differently, it says so; the full
list is [conformance/allowed_differences.yaml](../conformance/allowed_differences.yaml).

## The pattern this repo follows

Before diving into files, the target architecture for an agentic
application built this way has seven pieces:

1. **Browser frontend.** A thin UI that collects inputs and renders
   structured outputs. It never talks to a language model directly.
2. **API service.** A backend that owns request handling,
   authentication, input bounds, error handling, and safe response
   shaping.
3. **Deterministic orchestration.** A Microsoft Agent Framework workflow
   with a fixed sequence, at most one repair pass, and a predictable
   failure taxonomy. No language model chooses the route, so the tests
   can drive it with a fake client.
4. **Remote agents.** Each specialized reasoning role is composed from
   `/agents/<id>/agent.md` — instructions plus a bound model deployment —
   and published to Foundry as a versioned prompt agent.
5. **Typed contracts.** Every agent's reply is parsed into a typed model
   before the next step uses it. A reply that does not parse becomes a
   typed failure, never surfaced content.
6. **Synthetic data boundary.** Dealership records and saved plans are
   in-memory synthetic stores. Evidence defaults to fixtures; with
   `EVIDENCE_SOURCE=foundry_iq` the application retrieves evidence from an
   Azure AI Search knowledge base, which is the path Module 6 teaches.
7. **Observability boundary.** Only metadata (agent name, status,
   latency, coarse error code) leaves the process. Prompts,
   completions, and raw user text are never emitted.

This is the pattern to keep in mind while reading the rest of this
document.

## Repository layout

```
/agents/                       # Agent definitions (config-only), shared by both tracks
  data-analyst/
    agent.md                   # Source of truth for instructions
    manifest.yaml              # Source of truth for runtime metadata
                               #  incl. `foundry:` binding block
    schemas/                   # Agent-local input/output shapes
  support-recommender/
  validator/
  support-explainer/           # Standalone workshop agent, not a coordinator role

/.foundry/                     # Local, gitignored Foundry scratch state

/python/services/api/          # Python track: orchestration + FastAPI (no direct model calls)
  app/foundry_agents/          # ONLY place that imports the Foundry SDK
    maf_client.py              #   the Agent Framework model-client import
    maf_runtime.py             #   MafAgentRuntime (role -> Agent per call)
    role_definitions.py        #   roles from agent.md + deployment env vars
    error_mapping.py           #   provider errors -> app taxonomy
    prompt_envelope.py         #   compose_instructions(), shared with the publish scripts
    errors.py                  #   typed provider errors
  app/agents/{data_analyst,support_recommender,validator}/agent.py
                               # Role wrappers that call the remote adapter
  app/workflows/               # Agent Framework graph, executors, coordinator

/dotnet/services/api/          # .NET track: the same, as ASP.NET Core
  AgenticSupportGuide.Api/
    FoundryAgents/             # ONLY place that uses the Foundry SDK
      MafClient.cs             #   the Agent Framework model client
      MafRuntime.cs            #   MafAgentRuntime (role -> agent per call)
      RoleDefinitions.cs       #   roles from agent.md + deployment env vars
      ErrorMapping.cs          #   provider errors -> app taxonomy
      PromptEnvelope.cs        #   ComposeInstructions(), shared with the publish scripts
      Errors.cs                #   typed provider errors
    Agents/{DataAnalyst,SupportRecommender,Validator}/
                               # Role wrappers that call the remote adapter
    Workflows/                 # Agent Framework graph, executors, coordinator
  AgenticSupportGuide.Api.Tests/

/apps/web/                     # React + TS UI, shared by both tracks
/python/infra/                 # Terraform for Microsoft Foundry (Python track)
/dotnet/infra/                 # Terraform for Microsoft Foundry (.NET track)
/docs/                         # Architecture, security, ADRs, GenAIOps
/evals/                        # Synthetic evaluation cases
/conformance/                  # Recorded Python behaviour the .NET tests replay
/python/scripts/               # validate_agent_definitions.py, populate-env.ps1, ...
/dotnet/scripts/               # validate_agent_definitions.cs, populate-env.ps1, ...
```

## Source-of-truth rules

- **`/agents/<id>/agent.md`** — instructions the remote Foundry agent
  sees. No role-specific prompt text lives in application code, in either
  track.
- **`/agents/<id>/manifest.yaml`** — runtime metadata + the `foundry:`
  binding block (agent name, model deployment env var, temperature,
  response format).
- **`/agents/<id>/schemas/`** — the agent's input and output shapes,
  referenced from its manifest.
- **`/python/services/api/`** and **`/dotnet/services/api/`** — the
  orchestration engine and Foundry adapter, one per track.

## Independence rules

- Agents (in `/agents`) are configuration-only. No code lives under
  `/agents`.
- The three role wrappers do not import each other and do not import API
  internals. In Python, `app/agents/*/agent.py` stay out of `workflows/`,
  `main`, `models`, `plans_store` and `runtime_audit`; in .NET, nothing
  under `Agents/` uses `Program`, `Workflows`, the types in `Models.cs`,
  `SavedPlansStore` or `RuntimeAuditLog`.
- The coordinator is the only place all three agents meet.
- No file outside the model-client module (`app/foundry_agents/maf_client.py`
  in Python, `FoundryAgents/MafClient.cs` in .NET) may reference
  `AzureOpenAI` or `openai.`, or call chat completions directly
  (`chat.completions`; `CompleteChat` in .NET). This is asserted by
  `tests/test_agents_config.py` and `AgentsConfigTests.cs`. The retired
  Assistants API (`azure.ai.agents`; `Azure.AI.Agents.Persistent` in .NET)
  is banned everywhere by `tests/test_no_persisted_agents.py` and
  `NoPersistedAgentsTests.cs`, which also keep publishing symbols
  (`to_prompt_agent`, `create_version`; `ToPromptAgentAsync`,
  `CreateAgentVersion` in .NET) out of the request path - publishing
  is a GenAIOps step, allowlisted to `python/scripts/publish_prompt_agents.py`
  and `dotnet/scripts/publish_prompt_agents.cs`, and must never be triggered
  by a web request.

## Runtime execution

### MafAgentRuntime

Location:
[`python/services/api/app/foundry_agents/maf_runtime.py`](../python/services/api/app/foundry_agents/maf_runtime.py)
(Python),
[`dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafRuntime.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafRuntime.cs)
(.NET).

For a given role name (e.g. `data-analyst-agent`) and user message, the
adapter:

1. Looks up the role in its role definitions, loaded from
   `agents/<id>/agent.md` and its `manifest.yaml` at startup. Nothing is
   resolved against Foundry.
2. Calls `FoundryResponsesClientFactory` with the role's composed
   instructions. It makes a single-turn Responses call with storage off
   (`store=False` in Python, `StoredOutputEnabled = false` in .NET) and a
   strict JSON-schema response format bound to the role's contract — the
   agent folder's `schemas/output.schema.json`, which both tracks send
   unchanged — then returns the raw text.
3. Maps SDK-level failures into typed `FoundryProviderError` subclasses
   (`ConfigurationError`, `AuthError`, `ThrottledError`,
   `ContentFilterError`, `FoundryTimeoutError`, `RequiresActionError`,
   `FoundryRunError`). The .NET track has the same hierarchy under
   `FoundryProviderException`, each name ending in `Exception` instead
   (`ConfigurationException`, `AuthException`, and so on).

`python/scripts/validate_agent_definitions.py --check-connectivity`, or
`dotnet run dotnet/scripts/validate_agent_definitions.cs -- --check-connectivity`,
verifies the definitions load and the configured project answers, without
creating anything.

There is no local fallback: if the adapter cannot invoke the remote
agent, it raises. The coordinator translates that into a typed API
error.

### The three role classes

`DataAnalystAgent`, `SupportRecommendationAgent`, and `ValidatorAgent`
are now thin role wrappers, with the same names in both tracks. Each:

- Holds a reference to a `MafAgentRuntime`.
- Builds the role-specific user message (untrusted-data delimiters,
     concern text, prior-agent output as an untrusted block).
- Calls `runtime.invoke(role=..., user_message=...)` in Python, or
  `runtime.InvokeAsync(role, userMessage, ...)` in .NET.
- Parses the returned text as JSON and validates it with the internal
  typed contract for that role — a Pydantic model in Python, a record in
  `Contracts.cs` in .NET.

The Validator additionally runs deterministic checks in code against the
allowed catalog, required caveats, and required tier framing. The LLM
critique step delegates to the remote validator agent and is advisory
only — it cannot flip a deterministic pass to failure.

### Coordinator

Location:
[`python/services/api/app/workflows/`](../python/services/api/app/workflows/)
(Python),
[`dotnet/services/api/AgenticSupportGuide.Api/Workflows/`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/)
(.NET).

`AgentCoordinator.run()` (`RunAsync()` in .NET) builds a fresh Agent
Framework workflow with `build_plan_workflow(...)`
(`Graph.BuildPlanWorkflow(...)`) and runs it, reading the workflow's own
event stream. In Python:

```python
async for event in workflow.run(PlanState(concern=concern), stream=True):
    trace.observe(event)
    if event.type == "output":
        outputs.append(event.data)
```

In .NET:

```csharp
await using (var run = await InProcessExecution.RunStreamingAsync(workflow, new PlanState(concern), cancellationToken: cancellationToken))
{
    await foreach (var evt in run.WatchStreamAsync(cancellationToken))
    {
        trace.Observe(evt);
        switch (evt)
        {
            case WorkflowOutputEvent output when !output.HasTag(OutputTag.Intermediate):
                outputs.Add(output.Data);
                break;
            case ExecutorFailedEvent failedEvent when StepFailure(failedEvent.Data) is { } failed:
                failure = failed;
                break;
            case WorkflowErrorEvent errorEvent when StepFailure(errorEvent.Exception) is { } failed:
                failure ??= failed;
                break;
            case WorkflowErrorEvent { Exception: { } error }:
                // Anything else is a defect, not an outcome: surface it.
                throw new InvalidOperationException("The plan workflow failed.", error);
        }
    }
}
```

The trace rows the working nodes yield arrive as intermediate outputs, and
each node's latency is the time between its `executor_invoked` and
`executor_completed` events (`ExecutorInvokedEvent` and
`ExecutorCompletedEvent` in .NET). A node that cannot continue raises
`StepFailed` (`StepFailedException` in .NET), and here the frameworks
differ: Agent Framework for Python propagates it out of the run and the
coordinator catches it, while Agent Framework for .NET reports it as an
`ExecutorFailedEvent` on the event stream, which is where the .NET
coordinator picks it up. Either way the coordinator returns a
`CoordinatorResult` carrying a typed failure. A `Workflow` instance rejects
concurrent runs, so one is built per request.

The sequence itself lives in the graph, not in the coordinator.
[`graph.py`](../python/services/api/app/workflows/graph.py) and
[`Graph.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Graph.cs)
each wire six executors with six edges:

```
RetrieveEvidence -> Analyse -> Recommend -> Validate -> Finalise
                                   ^            |
                                   +-- repair --+--> Refuse
```

- Each agent's reply is parsed into its typed contract before the next
  executor sees it. A reply that does not parse raises `StepFailed`
  (`StepFailedException` in .NET) with `AGENT_INVALID_JSON`.
- `Validate` runs the deterministic checks plus an advisory LLM critique. The
  critique cannot flip a deterministic verdict.
- The repair bound is the `needs_repair` edge condition in
  [`plan.py`](../python/services/api/app/workflows/plan.py) (`Plan.NeedsRepair`
  in [`Plan.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Plan.cs)),
  not a loop: `MAX_RECOMMENDER_ATTEMPTS` (`Plan.MaxRecommenderAttempts`) is 2.
  When it is exhausted the `repair_exhausted` (`Plan.RepairExhausted`) edge
  routes to `Refuse`, which returns `VALIDATION_FAILED_AFTER_REPAIR`.
  `RetrieveEvidence` and `Analyse` are never re-run.
- The attempt count travels in the message, so neither track relies on the
  framework's own guard against a runaway cycle — which differs: Agent
  Framework for Python ends a run with an error after 100 supersteps, and
  Agent Framework for .NET has no superstep limit.

There is no path where `status == "ok"` returns without a validated
recommendation.

## The coordinator is not an agent

The coordinator is deterministic code, Python or C#, that builds the graph
and reads its events. It is not a fourth agent, does not talk to a base
model, and does not appear as a Foundry agent. This is intentional — it keeps
the sequence and the failure taxonomy in code the test suite can exercise
with a fake client.

## Trust boundaries

- User concern text is length-bounded before wrapping.
- Every untrusted block reaches the remote agent inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` delimiters.
- Prior-agent outputs are treated as untrusted data.
- Validator LLM critique text is filtered through `enforce_code()`
  (`PromptBlocks.EnforceCode` in .NET) — only strings matching
  `^[A-Z][A-Z0-9_]{3,59}$` survive.
- Trace metadata exposed to the UI contains only agent name, status,
  provider (`azure_foundry_responses` for the model steps, the retriever's
  own name — `fixture` or `foundry_iq` — for evidence retrieval), the served
  model, latency, token estimate, citation count, and enumerated
  issue/warning codes. No prompts or completions are exposed.

## Deployment / provisioning flow

The DevOps and GenAIOps halves are separate: Terraform provisions
infrastructure and never creates an agent. Publishing agents is a distinct,
explicit step run by `python/scripts/publish_prompt_agents.py` and
`python/scripts/publish_hosted_agent.py` (`dotnet/scripts/publish_prompt_agents.cs`
and `dotnet/scripts/publish_hosted_agent.cs` in .NET), and the running
application does not depend on it.

1. `terraform apply` in your track's Terraform root (`python/infra` or
   `dotnet/infra`) provisions the Foundry project and model deployments.
2. `python/scripts/populate-env.ps1` or `dotnet/scripts/populate-env.ps1`
   copies the outputs into the track's `.env` — `python/services/api/.env`
   or `dotnet/services/api/.env` (including
   `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and the per-role
   `FOUNDRY_MODEL_DEPLOYMENT_*` names).
3. Start the backend with `--env-file .env` (Python) or with
   `.\dotnet\scripts\run-backend.ps1` (.NET), which loads `.env` into the
   backend process. The app reads its configuration from the process
   environment and does not load `.env` implicitly, in either track.
4. `/api/health/details` reports `foundry_project_configured`,
   `agent_definitions_valid`, `model_deployments_configured`, and
   `service_side_remote_workflow_active`.

Editing `/agents/<id>/agent.md` takes effect after a backend restart: the
runtime loads and composes every role's instructions once at application
construction and caches them. The .NET build copies `agents/` next to the
app, so in that track the change also needs a rebuild, which
`run-backend.ps1` does when it starts. There is no publish step. Rolling back
is a revert commit plus a restart, not a redeployment.
`python python/scripts/validate_agent_definitions.py` or
`dotnet run dotnet/scripts/validate_agent_definitions.cs` validates the
definitions offline and prints an `instructions_hash` per role so you can
confirm a change landed.

See [`adr/0006-published-prompt-agents.md`](adr/0006-published-prompt-agents.md) and
[`adr/0001-foundry-project.md`](adr/0001-foundry-project.md).

## Dealer group isolation, evidence retrieval, and human review

Three concerns overlay the base workflow. They are all first-class in
the contracts and enforced in code, not in prompts.

### Dealer group isolation (`dealer_group_id`)

Every request carries a `dealer_group_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`. It is required by:

- `SupportPlanRequest` at the HTTP boundary.
- `DataAnalystOutput`, `SupportRecommendationDraft`, `ValidatorReport`,
  and `Citation`, the typed contracts of both tracks.
- The runtime audit and telemetry rows.

The Validator Agent raises `DRAFT_DEALER_GROUP_MISMATCH` and
`CROSS_DEALER_GROUP_CITATION` deterministically if anything drifts. See
[`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md).

### Evidence retrieval

The coordinator retrieves evidence **before** invoking any agent:

```
python/services/api/app/evidence/
  retrieval.py    # EvidenceRetriever Protocol (stable interface)
  fixtures.py     # FixtureEvidenceRetriever (synthetic per-dealer group)

dotnet/services/api/AgenticSupportGuide.Api/Evidence/
  Retrieval.cs    # IEvidenceRetriever interface (stable interface)
  Fixtures.cs     # FixtureEvidenceRetriever (synthetic per-dealer group)
```

The bundle is passed to the Support Recommendation Agent, which
attaches citations by ID. The Validator Agent checks citation
integrity (`MISSING_CITATIONS`, `UNKNOWN_CITATION_ID`,
`CROSS_DEALER_GROUP_CITATION`). See
[`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md).

### Human review lifecycle

Every recommendation is created in `human_review_state = pending_review`.
Allowed transitions live in
[`python/services/api/app/human_review.py`](../python/services/api/app/human_review.py)
and
[`dotnet/services/api/AgenticSupportGuide.Api/HumanReview.cs`](../dotnet/services/api/AgenticSupportGuide.Api/HumanReview.cs):

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

