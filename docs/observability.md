# Observability

This page first explains why observability for agentic apps is
different, then documents this repo's metadata-only approach.

## Observability for agentic apps

### What this means

Observability is the ability to explain, after the fact, what a
system did and why. For a multi-agent workflow, that means knowing
which agent ran, in what order, with what outcome, how long each hop
took, and how the request correlates across the whole sequence.

### Why traces matter

Each request in this repo triggers three sequential remote-agent
calls plus deterministic Python around them. Without a common
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
  `validation_failed`, `orchestration_budget_exhausted`),
- latency,
- coarse error code,
- token estimate when the provider returns usage,
- a `trace_id` that correlates the three agent steps of one request.

None of the above requires reading the model's prose.

### How trace IDs help debug multi-agent workflows

- The coordinator generates one `trace_id` per request and stamps it
  on every inter-agent message envelope.
- Every trace step in the response envelope carries the same
  `trace_id`, so a failed request can be pulled apart in Application
  Insights or the UI without touching prompts.

## How this repo implements metadata-only observability

### What is captured

When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, the backend
records one telemetry event per agent step through
`TelemetryRecorder.record()` in
[`services/api/app/telemetry.py`](../services/api/app/telemetry.py):

| Field | Example | Purpose |
| --- | --- | --- |
| `agent` | `data-analyst-agent` | Which agent step ran. |
| `status` | `ok`, `provider_timeout`, `provider_content_filter`, `validation_failed`, `orchestration_budget_exhausted` | Coarse-grained outcome. |
| `latency_ms` | `842` | Elapsed wall time. |
| `provider` | `azure_foundry_agents` | Fixed provider bucket. |
| `token_estimate` | `620` | When the provider returns usage. |
| `trace_id` | correlation-id-per-request | Ties the three agent steps of one request together. |

`TelemetryRecorder` also filters out any property key on a small
denylist (`prompt`, `completion`, `concern_text`, `raw_critique`,
`secret`, `api_key`, `token`). Even if callers try to attach an
unsafe field name, it never leaves the process.

### What is intentionally not captured

- Full or partial prompts.
- Full or partial completions.
- Raw concern text supplied by the user.
- Raw validator critique text.
- Secrets, tokens, API keys, or connection strings.
- Foundry endpoint URLs, project names, deployment names, assistant
  IDs, thread IDs, run IDs, resource IDs, subscription IDs, tenant
  IDs, or region names.
- Synthetic learner detail (labels, indicators, or scores).

### What the audit trail exposes

The `AI Audit` view and the `/api/audit/events` endpoint expose the
same metadata as the telemetry facade, plus a fixed synthetic user
label. Every runtime audit row is derived from the coordinator
result and carries only:

- timestamp (server-generated),
- endpoint (`/api/recommendations/support-plan`),
- context (`plan-generation`),
- provider bucket,
- duration,
- token estimate,
- status.

No agent-trace step ever surfaces prompt content, completion content,
raw validator critique, or issue-code strings that came directly
from model output. Validator LLM critique text is filtered through
`enforce_code()` in
[`services/api/app/agents/shared/sanitization.py`](../services/api/app/agents/shared/sanitization.py),
which requires uppercase snake_case codes of at least four characters
and drops anything else.

### How to verify

- Read
  [`services/api/app/telemetry.py`](../services/api/app/telemetry.py)
  and confirm the denylist.
- Read
  [`services/api/app/runtime_audit.py`](../services/api/app/runtime_audit.py)
  and confirm the fixed schema.
- Read the trace-metadata construction in
  [`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py)
  and confirm `provider="azure_foundry_agents"` and `model="remote"`
  are hard-coded rather than derived from endpoint or deployment
  strings.
- Run the privacy scanner:
  ```powershell
  cd services\api
  .\.venv\Scripts\Activate.ps1
  pytest tests\test_no_sensitive_content.py
  ```
- Run the health-details canary test:
  ```powershell
  pytest tests\test_health_details.py::test_health_details_does_not_leak_any_configured_env_values
  ```

### Common mistakes to avoid

- Adding `print()` calls that dump `response.text` from
  `FoundryRemoteAgentAdapter.invoke()`. The denylist protects the
  telemetry facade, not `stdout`.
- Passing the raw endpoint URL into a metric label "so we can filter
  by environment." Use a static environment tag applied at
  Application Insights level instead.
- Adding a `full_response` custom event to Application Insights for
  "debugging." Extend the metadata facade with a new coded field
  instead.

## Mapping to production observability

The `TelemetryRecorder.record()` shape is intentionally compatible
with Application Insights `TrackEvent` and OpenTelemetry span
attributes. Nothing in the shape needs to change to move to a real
backend; only the constructor plumbing does.

Suggested targets for a production deployment:

- **Azure Monitor** logs (KQL queries over `AgentTraceStep` metadata).
- **Application Insights** custom events (`agent_call`, `agent_step`,
  `validation_result`) for aggregate dashboards.
- **OpenTelemetry** distributed traces across agent hops if the
  three roles are split into independent services later. Preserve
  `trace_id` as the root span ID.
- **Azure Data Explorer / Kusto** for long-term retention of coarse
  operational metrics.

## Remaining gaps

- No dashboards, workbooks, or KQL queries are checked into this
  repo. Building them is straightforward on top of the shape above
  but is not implemented here.
- No OpenTelemetry integration is wired. Adding it would preserve
  the current schema and the current denylist.
- Prompt / completion capture for consented evaluation traffic is
  intentionally not implemented. If needed later, do it as an
  explicit opt-in feature with a separate telemetry sink and a
  review process — not by widening the metadata-only facade.
