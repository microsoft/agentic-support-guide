# Observability

This page first explains why observability for agentic apps is
different, then documents this repo's metadata-only approach. The app
exists in a Python track and a .NET track; both get their telemetry from
Microsoft Agent Framework, and where the two frameworks emit something
different, this page says so.

## Observability for agentic apps

### What this means

Observability is the ability to explain, after the fact, what a
system did and why. For a multi-agent workflow, that means knowing
which agent ran, in what order, with what outcome, how long each hop
took, and how the request correlates across the whole sequence.

### Why traces matter

Each request in this repo triggers three sequential remote-agent
calls plus deterministic code around them. Without a common
correlation ID, a failure in the second or third agent is impossible
to trace back to a specific request. Traces are what make
multi-agent workflows debuggable.

### Why prompt / completion logging is risky

- **Privacy.** A completion can echo a paraphrase of the user's
  concern text. Once logged, it may be reviewed by anyone with log
  access.
- **Cost.** Prompt/completion volume in a production support workflow
  can easily dominate telemetry cost.
- **Reviewability.** Absence of prompt/completion logging removes an
  entire class of privacy-review objections during customer
  conversations.

The simpler and safer stance is never to log prompts or completions
in the first place.

### What metadata is safe

Structural properties that describe **what happened**, not **what was
said**:

- agent role (e.g. `data-analyst-agent`),
- outcome status (`ok`, `provider_timeout`, `provider_content_filter`,
  `validation_failed`),
- latency,
- coarse error code,
- token estimate when the provider returns usage,
- a correlation ID that ties together the agent steps of one request.

None of the above requires reading the model's prose.

### How trace IDs help debug multi-agent workflows

- The coordinator generates one `correlation_id` per request and stamps
  it on the response envelope and on every audit row.
- The response envelope carries that one id alongside the ordered trace
  steps, so a failed request can be pulled apart in the UI without touching
  prompts. The id is deliberately **not** stamped on each individual step —
  see [What is captured](#what-is-captured) below.

## How this repo implements metadata-only observability

### What is captured

Observability is entirely Microsoft Agent Framework instrumentation. In the
Python track the whole integration is
[`python/services/api/app/observability.py`](../python/services/api/app/observability.py):

```python
configure_otel_providers(exporters=exporters or None)
enable_instrumentation()
```

In the .NET track,
[`dotnet/services/api/AgenticSupportGuide.Api/Observability.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Observability.cs)
is the export side, one tracer provider listening to the app's one
`ActivitySource`:

```csharp
public static TracerProviderBuilder Tracing(Action<TracerProviderBuilder> export)
{
    var builder = Sdk.CreateTracerProviderBuilder()
        .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService(Config.ServiceName, serviceVersion: Config.ServiceVersion))
        .AddSource(SourceName);
    export(builder);
    return builder.SetSampler(new AlwaysOnSampler());
}
```

`Configure` passes the Azure Monitor exporter as `export`. The sampler is the
one line that has no Python counterpart, and it is set last on purpose.
ASP.NET Core starts an activity for every request even though nothing here
exports it, and that activity is never sampled; a sampler that follows the
parent — the SDK's default, and the one the Azure Monitor exporter installs —
then drops every Agent Framework span beneath it. Without that line the
deployed .NET app exported nothing at all.
`Spans_inside_a_request_reach_the_exporter` in
[`ObservabilityTests.cs`](../dotnet/services/api/AgenticSupportGuide.Api.Tests/ObservabilityTests.cs)
sends a request through the real pipeline to keep it that way. The Python
server starts no request span, so there the workflow spans are roots.

The producing side is one call on each thing Agent Framework builds:
`.WithOpenTelemetry(activitySource: Observability.ActivitySource)` on the
workflow in
[`Workflows/Graph.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Graph.cs),
and `UseOpenTelemetry` on each agent and on its chat client in
[`FoundryAgents/MafClient.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs).
In both tracks, an app started without an Application Insights connection
string produces no spans at all: nothing is listening.

Agent Framework then emits OpenTelemetry spans for everything it runs. None of
them is a server span (model calls are `CLIENT`, and in .NET so are agent
calls; the rest are `INTERNAL` or `PRODUCER`), so the Azure Monitor exporter
writes them all to the `dependencies` table with span attributes in
`customDimensions`.

| Span | One per | Notable attributes |
| --- | --- | --- |
| `invoke_workflow support-plan` | request | `workflow.id`, `gen_ai.workflow.name` |
| `workflow.build` | graph construction | `workflow.definition` (the full graph as JSON) |
| `executor.process <id>` | node | `executor.id`, `executor.type` |
| `edge_group.process …` | edge delivery | `edge_group.delivered`, `edge_group.delivery_status` |
| `invoke_agent <agent>` (.NET: `invoke_agent <agent>(<id>)`) | agent call | `gen_ai.agent.name`, `error.type` |
| `chat <deployment>` | model call | `gen_ai.response.model`, input/output tokens, `error.type` |
| `workflow.session` (.NET only) | request, as the parent of `invoke_workflow` | |

The names match across the tracks except in two places. Agent Framework for
.NET names an agent span after the agent's name and its id, and the app sets
the id to the role, so the Python track's `invoke_agent data-analyst-agent`
is `invoke_agent data-analyst-agent(data-analyst-agent)` in .NET — the same
on every call, so it still groups cleanly. And Agent Framework for .NET opens
one more span per run, `workflow.session`, with `invoke_workflow` beneath it.

Spans are properly parented, so Application Insights' end-to-end transaction
view draws one request as a waterfall over the whole graph.

Prompt and completion text is excluded because Agent Framework's
sensitive-data setting defaults to off in both tracks. In Python,
`enable_sensitive_data` is False unless the `ENABLE_SENSITIVE_DATA`
environment variable is set, and this app never calls
`enable_sensitive_telemetry()`. In .NET, `EnableSensitiveData` is false
unless the `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` environment
variable is set, and this app never sets it. Set neither variable.
[`tests/test_observability.py`](../python/services/api/tests/test_observability.py)
and
[`ObservabilityTests.cs`](../dotnet/services/api/AgenticSupportGuide.Api.Tests/ObservabilityTests.cs)
each push a canary string through a real run and assert it appears in no
span, so the guarantee is tested rather than assumed.

### What is intentionally not captured

- Full or partial prompts.
- Full or partial completions.
- Raw concern text supplied by the user.
- Raw validator critique text.
- Secrets, tokens, API keys, or connection strings.
- Foundry endpoint URLs, project names, assistant
  IDs, thread IDs, run IDs, resource IDs, subscription IDs, tenant
  IDs, or region names.
- Synthetic dealership detail (labels, indicators, or scores).

The model deployment name is **not** excluded: Agent Framework records it as
`gen_ai.request.model` and in the `chat` span's name.

Failures are recorded differently by the two frameworks:

- **Python.** A failure records only its type: the framework sets
  `error.type` to the exception class name (for example
  `ChatClientException` or `StepFailed`), with no message and no stack
  trace, and marks the failed `executor.process` span and the
  `invoke_workflow` span as errors.
- **.NET.** A failed model call marks its `chat` and `invoke_agent` spans as
  errors, with `error.type` set to the exception's full type name (for
  example `System.AggregateException`) and the exception's message as the
  span's status description. A node that stops the run on purpose — no
  evidence, a provider error, an off-contract reply — throws
  `StepFailedException`, which Agent Framework for .NET reports as an
  executor-failed event on the workflow's event stream and does **not**
  record as a failed span: the `executor.process` and `invoke_workflow`
  spans keep an unset status.

So a query for failed spans (`success == false`) finds every failed model
call in both tracks. In .NET it does not find a run that a node stopped for
any other reason, such as missing evidence or an off-contract reply; those
runs show up by their `status` — in the API response and in the audit trail
below.

### What the audit trail exposes

The `AI Audit` view and the `/api/audit/events` endpoint expose
structural metadata only, plus a fixed synthetic user
label. Every runtime audit row is derived from the coordinator
result and carries:

- `event_id` and a server-generated timestamp,
- `endpoint` and `context`,
- `provider_model`, `duration_ms`, `token_estimate`, `status`,
- `correlation_id`, `dealer_group_id`,
- `evidence_count`, `citation_count`, `validator_status`,
- a fixed synthetic `user` label.

Two paths write rows. Plan generation uses endpoint
`/api/recommendations/support-plan` and context `plan-generation`. Human
review uses `/api/supports/plans/{plan_id}/review` and a
`review:<previous>-><new>` context, and sets `correlation_id` to the plan id.

No agent-trace step ever surfaces prompt content, completion content,
raw validator critique, or issue-code strings that came directly
from model output. Validator LLM critique text is filtered through
`enforce_code()` in
[`python/services/api/app/agents/shared/prompt_blocks.py`](../python/services/api/app/agents/shared/prompt_blocks.py)
(`PromptBlocks.EnforceCode` in
[`PromptBlocks.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/PromptBlocks.cs)),
which requires uppercase snake_case codes of at least four characters
and drops anything else.

### How to verify

- Read
  [`python/services/api/app/observability.py`](../python/services/api/app/observability.py)
  and confirm it never calls `enable_sensitive_telemetry()`; or read
  [`Observability.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Observability.cs)
  and
  [`MafClient.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs)
  and confirm nothing turns on `EnableSensitiveData`.
- Read
  [`python/services/api/app/runtime_audit.py`](../python/services/api/app/runtime_audit.py),
  or `RuntimeAuditLog` in
  [`Audit.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Audit.cs), and
  confirm the fixed schema.
- Read `_model_of` in
  [`python/services/api/app/workflows/executors.py`](../python/services/api/app/workflows/executors.py)
  (`Nodes.ModelOf` in
  [`Executors.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Executors.cs))
  and confirm a trace row's model comes from the agent's response, or
  `LOCAL_STEP_MODEL` (`Results.LocalStepModel`) when no model was called --
  the deployment that actually answered, not a constant. Module 7's routing
  demonstration depends on that. `PROVIDER_ID` is a constant, in
  [`python/services/api/app/foundry_agents/maf_runtime.py`](../python/services/api/app/foundry_agents/maf_runtime.py)
  (`MafAgentRuntime.ProviderId` in
  [`MafRuntime.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafRuntime.cs)).
- Run the privacy scanner. It is shared repo tooling written in Python, so
  whichever track you use it needs a Python with
  `maintenance/requirements.txt` installed; this command borrows the Python
  track's virtual environment:
  ```powershell
  cd maintenance
  ..\python\services\api\.venv\Scripts\python.exe -m pytest tests\test_no_sensitive_content.py
  ```
- Run the health-details canary test. Python, from `python/services/api`:
  ```powershell
  pytest tests\test_health_details.py::test_health_details_does_not_leak_any_configured_env_values
  ```
  .NET, from the repo root:
  ```powershell
  dotnet test --solution dotnet\AgenticSupportGuide.slnx --filter-method "*.Health_details_does_not_leak_any_configured_env_values"
  ```

### Common mistakes to avoid

- Adding `print()` calls that dump `response.text` from
  `MafAgentRuntime.invoke()` — or, in .NET, `Console.WriteLine` of
  `response.Text` from `MafAgentRuntime.InvokeAsync()`. Agent Framework's
  sensitive-data default governs spans, not `stdout`.
- Passing the raw endpoint URL into a metric label "so we can filter
  by environment." Use a static environment tag applied at
  Application Insights level instead.
- Adding a `full_response` custom event to Application Insights for
  "debugging." Add a new coded field to `AgentTraceStep`
  instead.

## Correlation IDs and dealer group context

The coordinator generates a `correlation_id` (a uuid4 string) per
recommendation request and stamps it on:

- The `RecommendationEnvelope`.
- Every runtime audit row.
- Every `review_transition` audit row raised by
  `POST /api/supports/plans/{plan_id}/review`.

It is deliberately **not** stamped on individual trace steps: the envelope
already carries it, and repeating it per step widens the surface for no gain.
`AgentTraceStep` has no `correlation_id` field, and a test asserts that.

The trace step names are `evidence-retrieval`, `data-analyst-agent`,
`support-recommendation-agent`, `validator-agent`, plus a `…:repair` suffix
when a step is retried.

Alongside `correlation_id`, these fields are safe to log. Only
`citation_count` is per hop; the rest are once per request:

| Field | Where |
| --- | --- |
| `citation_count` | Each `AgentTraceStep`, and the envelope |
| `dealer_group_id` | Envelope, and each audit row |
| `evidence_count` | Envelope, and the audit row (`runtime_audit.py` / `Audit.cs`) |
| `validator_status` | Envelope, and the audit row (`runtime_audit.py` / `Audit.cs`) |
| `citations_proposed` / `citations_accepted` | Envelope |
| `resources_proposed` / `resources_accepted` / `unknown_resource_ids` | Envelope |
| `attempts`, `validation_reached`, `deterministic_checks_total` | Envelope |

The envelope fields drive the UI's enforcement receipt. They are counts and
enumerated codes only — never prompt or completion text. A field is `null`
rather than zero when it was not measured, so "not reached" stays
distinguishable from "measured zero".

That distinction is load-bearing. A run that stops at retrieval never
reaches the recommender or the validator, so reporting `citations_proposed`
or `deterministic_checks_total` as `0` would claim those stages ran and found
nothing. The audit row is a fixed-shape record and stores `0` for an
unreached stage; the envelope keeps the `null`.

None of these are prompts or completions. They allow a support
engineer to trace a single request end-to-end (or reconstruct a
review-and-approval sequence) without ever seeing raw model text.

## Mapping to production observability

Spans are already OpenTelemetry, emitted by Agent Framework against the
`gen_ai` semantic conventions, so nothing in the shape is this repo's to
change. Pointing them at a different backend is a matter of passing a
different exporter to `configure_otel_providers` in Python, or adding one to
the tracer provider builder in `Observability.cs` in .NET.

Suggested targets for a production deployment:

- **Azure Monitor** logs (KQL over the `dependencies` table).
- **Application Insights** end-to-end transaction view, which renders one
  request as a waterfall over the whole graph.
- **Any OTLP collector**, if the three roles are later split into independent
  services. Span parenting already carries the trace across hops.
- **Azure Data Explorer / Kusto** for long-term retention of coarse
  operational metrics.

## Remaining gaps

- No dashboards or workbooks are checked into this repo. Module 10 does
  check in the KQL queries the workshop uses; building saved workbooks on
  top of them is straightforward but is not implemented here.
- Prompt / completion capture for consented evaluation traffic is
  intentionally not implemented. If needed later, do it as an
  explicit opt-in feature with a separate telemetry sink and a
  review process — not by widening `AgentTraceStep`.
