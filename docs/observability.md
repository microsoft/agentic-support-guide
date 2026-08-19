# Observability

This prototype uses lightweight, metadata-only observability. Nothing
that could contain synthetic learner detail, prompt text, completion
text, raw validator critique, secrets, endpoints, or resource IDs is
ever emitted.

## What is captured

When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, the backend records
one telemetry event per agent step through the
`TelemetryRecorder.record()` facade in
[`services/api/app/telemetry.py`](../services/api/app/telemetry.py):

| Field | Example | Purpose |
| --- | --- | --- |
| `agent` | `data-analyst-agent` | Which agent step ran. |
| `status` | `ok`, `provider_timeout`, `provider_content_filter`, `validation_failed`, `orchestration_budget_exhausted` | Coarse-grained outcome. |
| `latency_ms` | `842` | Elapsed wall time. |
| `provider_model` | `azure-openai / <deployment>` | Provider/model bucket (deployment name only, no endpoint). |
| `token_estimate` | `620` | When the provider returns usage. |
| `trace_id` | correlation-id-per-request | Ties the three agent steps of one request together. |

The `TelemetryRecorder` also filters out any property key on a small
denylist (`prompt`, `completion`, `concern_text`, `raw_critique`,
`secret`, `api_key`, `token`). Even if callers try to attach an unsafe
field name, it never leaves the process.

## What is intentionally not captured

- Full or partial prompts.
- Full or partial completions.
- Raw concern text supplied by the user.
- Raw validator critique text.
- Secrets, tokens, API keys, or connection strings.
- Foundry endpoint URLs, project names, resource IDs, subscription IDs,
  tenant IDs, or region names.
- Synthetic learner detail (labels, indicators, or scores).

## What the audit trail exposes

The `AI Audit` view and the `/api/audit/events` endpoint expose the same
metadata as the telemetry facade, plus a fixed synthetic user label
`Staff S-01`. Every runtime audit row is derived from the coordinator
result and carries only:

- timestamp (server-generated),
- endpoint (`/api/recommendations/support-plan`),
- context (`plan-generation`),
- provider/model bucket,
- duration,
- token estimate,
- status.

No agent-trace step ever surfaces prompt content, completion content,
raw validator critique, or issue-code strings that came directly from
model output. Validator LLM critique text is filtered through
`enforce_code()` in
[`services/api/app/agents/shared/sanitization.py`](../services/api/app/agents/shared/sanitization.py),
which requires uppercase snake_case codes of at least 4 characters and
drops anything else.

## Mapping to production observability

For a production deployment, extend the facade to emit into:

- **Azure Monitor** logs (KQL queries over `AgentTraceStep` metadata).
- **Application Insights** custom events (`agent_call`, `agent_step`,
  `validation_result`) for aggregate dashboards.
- **OpenTelemetry** distributed traces across agent hops, especially if
  the three agents are split into independent services later. Preserve
  `trace_id` as the root span ID.
- **Azure Data Explorer / Kusto** for long-term retention of coarse
  operational metrics.

The `TelemetryRecorder.record()` shape is intentionally compatible with
Application Insights `TrackEvent` and OpenTelemetry span attributes.
Nothing in the shape needs to change to move to a real backend; only
the constructor plumbing does.

## Why not capture prompts and completions

- **Privacy.** A single completion may accidentally include a paraphrase
  of an operator's concern text. Rather than filter after the fact, the
  simpler and safer stance is never to log any of it.
- **Cost.** Prompt/completion volume in a production support workflow
  can easily dominate telemetry cost.
- **Reviewability.** Absence of prompt/completion logging removes an
  entire class of privacy-review objections during customer conversations.

If a future workload legitimately needs prompt/completion capture (for
example, quality evaluation over user-consented traffic), do it as an
explicit opt-in feature with a separate telemetry sink and a review
process — not by widening the metadata-only facade in this repo.
