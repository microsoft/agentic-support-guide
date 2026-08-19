# Security and privacy

This page first explains the general security and privacy pattern for
agentic applications, then documents how this repo applies each piece.
It uses plain language and does not assume prior security expertise.

## The pattern for agentic apps

### What this means

Agentic applications introduce risks that traditional web apps do not:
a language model can be tricked with prompt injection, an agent can be
handed data it should not see, and telemetry can accidentally record
sensitive text. A safe design draws bright lines around each of these.

### Why it matters

Once a prompt or completion is logged, it may be reviewed by anyone
with access to the log. Once an agent is trusted with real user data,
a single injection can exfiltrate it. Once auth uses a long-lived key,
that key becomes a permanent liability. Each risk is easier to prevent
by design than to remove later.

### Best-practice pattern

1. **Data minimization.** The workload sees the smallest set of fields
   that answers the request.
2. **Synthetic / non-prod data for demos.** Nothing shown to a
   customer should represent a real person.
3. **Prompt-injection boundaries.** Untrusted text (from the user or
   an upstream agent) is wrapped in an explicit "this is data, not
   instructions" delimiter and stripped of known injection patterns.
4. **Agent-to-agent trust boundaries.** One agent's output is treated
   as untrusted data by the next agent, not as an authoritative
   instruction. Every hop validates against a schema.
5. **Keyless auth.** The application never holds a static API key.
6. **RBAC.** The application principal has the least privilege it
   needs to call the model, and nothing else.
7. **No prompt / completion logging.** Traces carry structural
   metadata only.
8. **Metadata-only observability.** The observability pipeline cannot
   accidentally receive sensitive text because the code path never
   passes it in.
9. **Human review.** Every generated recommendation carries an
   explicit "human review required" caveat, and the workload does not
   make final decisions.

## How this repo applies each pattern

### Data minimization

- The backend reads only the synthetic in-memory repositories in
  [`services/api/app/repositories.py`](../services/api/app/repositories.py).
- No database, no external ingestion, no file-system state beyond the
  in-memory saved-plans store.
- The FastAPI request models bound and validate all inputs at the
  boundary.

**How to verify.** Read
[`services/api/app/models.py`](../services/api/app/models.py) for the
Pydantic request models and
[`services/api/app/repositories.py`](../services/api/app/repositories.py)
for the synthetic-only data path.

### Synthetic / non-prod data

- Every learner, school, KPI, and trend value is produced by
  deterministic factories seeded with `SEED = 20260101` in
  [`services/api/app/config.py`](../services/api/app/config.py).
- No demo path reads from a live database.

**How to verify.** Grep for `SEED` and inspect
[`services/api/app/mock_data.py`](../services/api/app/mock_data.py).
The privacy scanner test in
[`services/api/tests/test_no_sensitive_content.py`](../services/api/tests/test_no_sensitive_content.py)
enforces that only allow-listed placeholder values appear anywhere.

### Prompt-injection boundaries

- Free-text user input is sanitized through `sanitize_free_text()`:
  control characters stripped, common injection phrases replaced with
  `[filtered]`, delimiter tags removed, whitespace collapsed, length
  clipped to 1000 characters.
- Every untrusted block reaches the remote agent inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` markers.
- The system-level instructions (in `agent.md`) tell the remote agent
  to treat wrapped blocks as data only.

**How to verify.** Read
[`services/api/app/agents/shared/sanitization.py`](../services/api/app/agents/shared/sanitization.py).
Run `pytest -k sanitization` for the covering tests.

### Agent-to-agent trust boundaries

- The three agents exchange messages only through the JSON Schemas in
  [`/contracts/v1`](../contracts/v1). The coordinator validates each
  message against the corresponding schema before forwarding.
- The Support Recommendation Agent receives the Data Analyst output
  wrapped as an untrusted block, not injected as instructions.
- The Validator Agent receives both prior outputs the same way.
- Validator repair guidance sent back to the recommender is drawn
  from fixed templates keyed by issue code — not from raw LLM
  critique text.

**How to verify.** Read `_protocol_validate` and the payload builders
in [`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py).

### Keyless auth

- The Foundry SDK client acquires bearer tokens through
  `DefaultAzureCredential`, which uses `az login`, managed identity,
  or workload identity. No API key is stored.
- Terraform sets `local_auth_enabled = false` on the AI Services
  account and never reads model keys. No key is written to Key Vault.

**How to verify.** Read
[`services/api/app/foundry_agents/sdk_client.py`](../services/api/app/foundry_agents/sdk_client.py)
and
[`infra/ai_foundry.tf`](../infra/ai_foundry.tf) (the
`local_auth_enabled` setting on the `azurerm_cognitive_account`
resource).

### RBAC

- Terraform assigns the app's principal the `Cognitive Services
  OpenAI User` role at the AI Services account scope. No other role
  is granted.
- The principal is either the current signed-in user (via
  `data.azurerm_client_config`) or an explicit `principal_id` passed
  through `terraform.tfvars`.

**How to verify.** Search for `azurerm_role_assignment` in
[`/infra`](../infra).

### No prompt / completion logging

- Telemetry captures structural metadata only: agent name, status,
  provider, latency, coarse error category, trace ID.
- `TelemetryRecorder` has a hard denylist of unsafe keys
  (`prompt`, `completion`, `concern_text`, `raw_critique`, `secret`,
  `api_key`, `token`).
- The audit endpoint returns seeded synthetic rows plus in-memory
  metadata rows and never surfaces prompts, completions, raw
  concern text, or secrets.

**How to verify.** Read
[`services/api/app/telemetry.py`](../services/api/app/telemetry.py)
and
[`services/api/app/runtime_audit.py`](../services/api/app/runtime_audit.py).
See [Observability](observability.md) for the safe schema.

### Metadata-only observability

- See the dedicated [Observability](observability.md) doc.
- `/api/health/details` reports posture flags but never includes the
  configured endpoint URL, deployment name, connection string, or
  token.

**How to verify.** Inspect
[`services/api/app/diagnostics.py`](../services/api/app/diagnostics.py)
and the test at
[`services/api/tests/test_health_details.py`](../services/api/tests/test_health_details.py)
that plants canary values in settings and asserts they never appear
in the response body.

### Human review

- Every recommendation returned to the UI contains a "human review is
  required" caveat, enforced deterministically by the Validator Agent.
- The UI shows a persistent prototype banner and a demo scope
  disclaimer.
- The prototype does not make final educational, legal, compliance,
  medical, disability, or placement determinations.

**How to verify.** Read the caveat checks in the Validator Agent and
the persistent banner in the frontend layout.

## Secret handling

- `.env`, `terraform.tfvars`, and `.foundry/agent-bindings.local.json`
  are gitignored.
- `.env.example`, `terraform.tfvars.example`, and
  `.foundry/agent-bindings.example.json` contain placeholder values
  only.
- Application Insights connection string is marked `sensitive = true`
  in Terraform outputs.
- The privacy scanner test flags 32+ character base64/hex values on
  lines beginning with `AZURE_*=`.
- `.foundry/agent-bindings.local.json` contains only assistant IDs
  and metadata hashes. It never contains tokens or connection
  strings, and the runtime refuses to use it if the
  `project_endpoint_hash` does not match the configured endpoint.

## Validation gates

- Every remote-agent response is parsed and Pydantic-validated
  against a typed internal contract, and then validated by the JSON
  Schema in [`/contracts/v1`](../contracts/v1) before being forwarded.
- If validation still fails after one repair pass, no recommendation
  is returned; the API returns a typed `validation_failed` envelope
  with safe issue codes.

## Content-filter handling

- The Foundry adapter classifies content-filter responses (via
  terminal run status and error code) and raises
  `ContentFilterError("CONTENT_FILTER", ...)`.
- The coordinator maps that to a `provider_content_filter` status
  code and returns a safe user-facing message.
- The UI shows a distinct safe state for content-filter blocks with
  no raw model text.

## Common mistakes to avoid

- Adding a "just for debugging" logger that prints the outgoing
  prompt or the model response. The denylist prevents the metadata
  facade from carrying such fields, but there is no filter for a
  developer-added `print()`.
- Loosening the `sanitize_free_text` regex to "let the model see the
  full raw input." The regex is intentionally strict; broaden the
  design (for example, quote-only insertion of the raw text) rather
  than removing the filter.
- Storing bindings in a shared drive. Bindings are environment-
  specific and gitignored on purpose.

## What the prototype is not

- Not a real AI-safety review pipeline.
- Not a substitute for human review.
- Not a medical, legal, disability, placement, or compliance
  determination system.
