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
- The response envelope carries that one id alongside the ordered trace
  steps, so a failed request can be pulled apart in the UI without touching
  prompts. The id is deliberately **not** stamped on each individual step —
  see [What is captured](#what-is-captured) below.

## How this repo implements metadata-only observability

### What is captured

Observability is entirely Microsoft Agent Framework instrumentation. The whole
integration is
[`services/api/app/observability.py`](../services/api/app/observability.py):

```python
configure_otel_providers(exporters=exporters or None)
enable_instrumentation()
```

Agent Framework then emits OpenTelemetry spans for everything it runs. All of
them are `INTERNAL` or `PRODUCER`, so the Azure Monitor exporter writes them
to the `dependencies` table with span attributes in `customDimensions`.

| Span | One per | Notable attributes |
| --- | --- | --- |
| `workflow.run` | request | `workflow.id`, `workflow.name` |
| `workflow.build` | graph construction | `workflow.definition` (the full graph as JSON) |
| `executor.process <id>` | node | `executor.id`, `executor.type` |
| `edge_group.process …` | edge delivery | `edge_group.delivered`, `edge_group.delivery_status` |
| `chat` / `invoke_agent` | model call | `gen_ai.response.model`, input/output tokens, `error.type` |

Spans are properly parented, so Application Insights' end-to-end transaction
view draws one request as a waterfall over the whole graph.

Prompt and completion text is excluded because Agent Framework's
`enable_sensitive_data` setting defaults to False. This app never calls
`enable_sensitive_telemetry()`.
[`tests/test_observability.py`](../services/api/tests/test_observability.py)
pushes a canary string through a real run and asserts it appears in no span,
so the guarantee is tested rather than assumed.

### What is intentionally not captured

- Full or partial prompts.
- Full or partial completions.
- Raw concern text supplied by the user.
- Raw validator critique text.
- Secrets, tokens, API keys, or connection strings.
- Foundry endpoint URLs, project names, deployment names, assistant
  IDs, thread IDs, run IDs, resource IDs, subscription IDs, tenant
  IDs, or region names.
- Synthetic dealership detail (labels, indicators, or scores).

### What the audit trail exposes

The `AI Audit` view and the `/api/audit/events` endpoint expose
structural metadata only, plus a fixed synthetic user
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
[`services/api/app/agents/shared/prompt_blocks.py`](../services/api/app/agents/shared/prompt_blocks.py),
which requires uppercase snake_case codes of at least four characters
and drops anything else.

### How to verify

- Read
  [`services/api/app/observability.py`](../services/api/app/observability.py)
  and confirm it never calls `enable_sensitive_telemetry()`.
- Read
  [`services/api/app/runtime_audit.py`](../services/api/app/runtime_audit.py)
  and confirm the fixed schema.
- Read how a trace step is built in
  [`services/api/app/workflows/steps.py`](../services/api/app/workflows/steps.py)
  and confirm the model comes from `served_model or LOCAL_STEP_MODEL` --
  the deployment that actually answered, not a constant. Module 7's routing
  demonstration depends on that. `PROVIDER_ID` is a constant, in
  [`services/api/app/foundry_agents/maf_runtime.py`](../services/api/app/foundry_agents/maf_runtime.py).
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
  `MafAgentRuntime.invoke()`. Agent Framework's sensitive-data default
  governs spans, not `stdout`.
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
| `evidence_count` | Envelope, and the audit row (`runtime_audit.py`) |
| `validator_status` | Envelope, and the audit row (`runtime_audit.py`) |
| `citations_proposed` / `citations_accepted` | Envelope |
| `resources_proposed` / `resources_accepted` / `unknown_resource_ids` | Envelope |
| `attempts`, `validation_reached`, `deterministic_checks_total` | Envelope |

The envelope fields drive the UI's enforcement receipt. They are counts and
enumerated codes only — never prompt or completion text. A field is omitted
rather than zeroed when it was not measured, so "not reached" stays
distinguishable from "measured zero".

None of these are prompts or completions. They allow a support
engineer to trace a single request end-to-end (or reconstruct a
review-and-approval sequence) without ever seeing raw model text.

## Mapping to production observability

Spans are already OpenTelemetry, emitted by Agent Framework against the
`gen_ai` semantic conventions, so nothing in the shape is this repo's to
change. Pointing them at a different backend is a matter of passing a
different exporter to `configure_otel_providers`.

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
