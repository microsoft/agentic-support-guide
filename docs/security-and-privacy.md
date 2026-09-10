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
[`services/api/app/foundry_agents/maf_client.py`](../services/api/app/foundry_agents/maf_client.py)
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

  are gitignored.
- `.env.example`, `terraform.tfvars.example`, and
  `services/api/.env.example` contain placeholder values
  only.
- Application Insights connection string is marked `sensitive = true`
  in Terraform outputs.
- The privacy scanner test flags 32+ character base64/hex values on
  lines beginning with `AZURE_*=`.
  and metadata hashes. It never contains tokens or connection
  strings, and the runtime refuses to use it if the
  the configured project endpoint does not match the configured endpoint.

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

## Caller authentication

There is no user sign-in. The API is authenticated to, but nobody logs in.

The web tier serves the SPA and reverse-proxies `/api/*` to the API,
attaching a shared key server-side (`apps/web/server.js`). The API
rejects anything without that key, so its public hostname cannot be
called directly.

The key never reaches the browser. A React bundle cannot keep a secret -
anything it carried would be readable in DevTools - which is why the
proxy exists at all rather than the SPA holding a credential. A smoke
check asserts the deployed bundle contains neither the key nor the API
hostname, because either would mean the proxy had been bypassed.

- `/api/health` is the only anonymous route. The deploy polls it to find
  out which build is serving, before the web tier is up. It returns a
  status, a version and a build id.
- `/api/health/details` requires the key. It reports evidence source,
  knowledge base and readiness flags, which is reconnaissance for anyone
  choosing what to attack, and nothing in the deploy path needs it.
- A deployed API with no key configured returns 503 rather than serving
  unauthenticated. Forgetting a setting must not be the same as turning
  authentication off.
- Local development needs no key: the Vite dev server proxies `/api` to
  uvicorn, mirroring production, and the API only insists on a key when
  it detects App Service.

### What this does not protect

**The web tier is anonymous.** Anyone with the UI URL can use the app,
and the proxy will attach the key on their behalf. The key stops the API
being called directly; it does nothing about the front door.

That is a deliberate consequence of "no user login". Without an identity
nothing can distinguish the owner from any other visitor, so the only
remaining control is a network boundary: `web_allowed_ip_ranges` puts an
IP allowlist on the web app. It is empty by default, because a learner
moving between office, home and a hotspot will lock themselves out with
no way to tell why.

The realistic exposure is model quota, not data - the records are
synthetic. The web tier rate-limits the front door (10 recommendations
per minute per address, 4 concurrent, 30 requests per minute overall,
256 KB bodies), which bounds what a stranger can spend without an
account. The limit lives in the proxy rather than the API so that
`scripts/load_test.py`, which calls the API directly with the key, can
still measure real capacity in Module 5.

It is per instance and in memory, so it resets on restart and would
multiply if the app scaled out. It is a cost guard, not a security
boundary. `model_capacity` and a budget alert remain the backstop.

### What was removed, and why

An earlier version used App Service Easy Auth with per-user Entra
sign-in and district assignments keyed on object id. It was removed
because each learner deploys their own stack: the deploying learner was
the only legitimate user, so per-user identity added a sign-in flow, an
app registration, and several failure modes while defending against a
threat that did not exist.

The cost is real and worth stating plainly: **district isolation is now
a demonstrated pattern, not an enforced control.** The UI picks a
district and the API validates that it exists. Nothing answers "is this
caller allowed that district", because there is no caller identity to
ask about. Retrieval filtering, cross-district citation checks and the
validator's district assertions all still run - they keep a *request*
inside one district, which is what the workshop is teaching.

## District isolation

Every request carries a `district_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`, and the roster is served to the UI from
`/api/supports/options` so no district name is hardcoded in the bundle.
It is enforced at four layers:

- **HTTP** - required by `SupportPlanRequest`.
- **Contracts** - required in every JSON Schema in `/contracts/v1/`.
- **Coordinator** - propagated to every agent context and stamped on
  every envelope payload.
- **Validator Agent** - deterministic checks
  (`DRAFT_DISTRICT_MISMATCH`, `CROSS_DISTRICT_CITATION`,
  `UNKNOWN_CITATION_ID`) reject any drift.

These keep evidence for one request inside one district. None of them is
an authorization check, and with no caller identity there is nothing to
authorize against - see above.

### Known gap: the synthetic roster is not district-scoped

`Learner`, `AssessmentRecord` and `BehaviorRecord` carry no
`district_id`. Every caller sees the same synthetic cohort from
`/api/learners`, `/api/dashboard/summary`, `/api/assessments/summary`,
`/api/behavior/summary` and `/api/supports/options`.

This is a property of the mock dataset, not of the request pipeline. A
real deployment must add `district_id` to these records and filter on
it, exactly as the evidence layer already does for citations.

The target production topology gives each district its own Microsoft
Fabric workspace and lakehouse. This repo ships only synthetic
per-district fixtures via `FixtureEvidenceRetriever`. See
[`adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md).

## Human review

Every recommendation is created in `human_review_state = pending_review`.
Allowed transitions live in
[`services/api/app/human_review.py`](../services/api/app/human_review.py):

```
draft            -> pending_review
pending_review   -> approved | rejected
rejected         -> pending_review
approved         (terminal)
```

Transitions:

- Are made through `POST /api/supports/plans/{plan_id}/review`.
- Are validated against the state machine; invalid transitions raise
  `InvalidReviewTransitionError` (HTTP 409).
- Are recorded in the runtime audit log as `review_transition` events
  with `correlation_id`, `district_id`, old state, new state, and a
  reviewer identifier. No prompt or completion text is stored.

Approval is terminal in the demo. Production would layer on district
approver identity, signing, and workflow escalation. That is out of
scope for this prototype.

## Evidence-backed output

Every passing recommendation attaches at least one citation. The
Validator Agent rejects `MISSING_CITATIONS`,
`CROSS_DISTRICT_CITATION`, and `UNKNOWN_CITATION_ID`. The
`Citation` type includes only safe fields (`citation_id`,
`district_id`, `source_type`, `source_title`, `section_or_page`,
`evidence_summary`, `source_ref`, `retrieved_at`, `confidence`).
It never carries a raw document body.

See [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md).

## Correlation IDs and safe audit

The coordinator generates a `correlation_id` per request. Audit rows
carry `correlation_id`, `district_id`, `evidence_count`,
`citation_count`, and `validator_status`. None of them contain
prompts, completions, thread IDs, or run IDs. See
[`observability.md`](observability.md).
