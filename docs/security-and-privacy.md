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

App Service Easy Auth sits in front of the API and validates the Entra
token before a request reaches application code. Signature, issuer,
audience and expiry are the platform's job; the app never parses a JWT
or caches signing keys.

- Unauthenticated requests get **401**, not a redirect. Every caller is
  a SPA holding a bearer token or a script, and both break on a 302 to
  a login page.
- Only `/api/health` and `/api/health/details` are anonymous, so a
  deploy can check which build is serving before anyone signs in.
- `auth_settings_v2.allowed_audiences` lists **both** the bare app-ID
  GUID and `api://<app-id>`. A v2.0 access token carries the GUID; if
  only the URI is listed, Easy Auth rejects every valid token with a
  bodiless 403.
- Easy Auth changes need `az webapp restart`. Terraform state can show
  `require_authentication = true` while the running worker still serves
  anonymous traffic.

The UI signs in with MSAL using the authorization-code flow with PKCE
and no client secret, caching tokens in `sessionStorage` so a token
does not outlive the browser session on a shared workshop machine.

Local development runs with `API_AUTH_MODE=disabled`, because a local
uvicorn has no Easy Auth in front of it to inject the principal header.
That mode returns a development principal with facilitator rights over
every district, so the app refuses to honour it whenever App Service is
detected (`WEBSITE_SITE_NAME` is set). A deployed API with auth turned
off therefore returns 401 to everyone rather than serving everyone -
unusable, but not open. `/api/health/details` reports the effective mode.

### The trust boundary

The app does not verify the `x-ms-client-principal` header. Easy Auth
strips any client-supplied copy and injects its own, so within the
platform boundary the header is authoritative. This is a deliberate
choice: owning JWKS caching and key rollover in application code would
be a liability with no upside.

The consequence is that anything able to reach the container directly,
bypassing Easy Auth, could present any identity it liked. That is why
the fail-closed check above exists, and why
`test_a_forged_principal_header_is_honoured_documenting_the_trust_model`
pins the behaviour: it is a recorded decision, not an oversight.

## District isolation

Every request carries a `district_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`. It is enforced at five layers:

- **Authorization** - `require_district` rejects any district not
  assigned to the caller with a **403**, before any data access or
  model call. This is the layer that matters: the four below faithfully
  honour whatever district the caller asks for, so without it a caller
  simply chose their own `district_id` and the rest of the stack
  obliged.
- **HTTP** - required by `SupportPlanRequest`.
- **Contracts** - required in every JSON Schema in `/contracts/v1/`.
- **Coordinator** - propagated to every agent context and stamped on
  every envelope payload.
- **Validator Agent** - deterministic checks
  (`DRAFT_DISTRICT_MISMATCH`, `CROSS_DISTRICT_CITATION`,
  `UNKNOWN_CITATION_ID`) reject any drift.

Assignments live in `district_assignments` in `terraform.tfvars`, keyed
on Entra object ID because it is immutable and unique within the tenant,
unlike a UPN which can be reassigned to a different person. An account
with no assignment can sign in and sees nothing; a blanket default grant
would hand every account in the tenant access to every district.

`require_district` deliberately does not distinguish "no such district"
from "not yours" - that difference would let a caller enumerate which
districts exist.

Reads are filtered rather than refused: saved plans and the audit feed
return only the caller's districts, so a shared demo environment does
not leak another learner's activity.

### Known gap: the synthetic roster is not district-scoped

`Learner`, `AssessmentRecord` and `BehaviorRecord` carry no
`district_id`. Every caller sees the same synthetic cohort from
`/api/learners`, `/api/dashboard/summary`, `/api/assessments/summary`,
`/api/behavior/summary` and `/api/supports/options`. Those routes still
require an authenticated principal, but they have nothing to filter on,
and nothing stops a caller pairing any learner ID with any district they
are assigned to.

This is a property of the mock dataset, not of the authorization layer.
It does not leak across districts today because there are no
per-district learners to leak - but a real deployment must add
`district_id` to these records and filter on it, exactly as the
evidence layer already does for citations.

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
