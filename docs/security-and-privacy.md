# Security and privacy

This page first explains the general security and privacy pattern for
agentic applications, then documents how this repo applies each piece.
It uses plain language and does not assume prior security expertise.
The app exists in a Python track and a .NET track that apply every control
the same way; where a control lives in code, both tracks' files are named.

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
   instructions" delimiter. Filtering obfuscated injections is out of
   scope; the validator decides what ships.
4. **Agent-to-agent trust boundaries.** One agent's output is treated
   as untrusted data by the next agent, not as an authoritative
   instruction. Every hop validates against a schema.
5. **Keyless auth to Foundry.** The application holds no static credential
   for the model provider; it authenticates with Microsoft Entra ID. Inbound
   API requests are a separate matter and do use a shared key.
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
  [`python/services/api/app/repositories.py`](../python/services/api/app/repositories.py)
  or
  [`dotnet/services/api/AgenticSupportGuide.Api/Repositories.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Repositories.cs).
- No database and no file-system state beyond the in-memory saved-plans
  store. Evidence retrieval is the one external read, and only when
  `EVIDENCE_SOURCE=foundry_iq` points it at Azure AI Search.
- The API's request models bound and validate all inputs at the
  boundary.

**How to verify.** Read
[`python/services/api/app/models.py`](../python/services/api/app/models.py) for the
Pydantic request models and
[`python/services/api/app/repositories.py`](../python/services/api/app/repositories.py)
for the synthetic-only data path; in .NET,
[`RequestModels.cs`](../dotnet/services/api/AgenticSupportGuide.Api/RequestModels.cs)
and `Repositories.cs`.

### Synthetic / non-prod data

- Every dealership, region, KPI, and trend value is produced by
  deterministic factories seeded with `SEED = 20260101` in
  [`python/services/api/app/config.py`](../python/services/api/app/config.py)
  (`Config.Seed` in
  [`Config.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Config.cs)).
  Both tracks generate byte-identical data from it; the conformance tests
  check that.
- No demo path reads from a live database.

**How to verify.** Grep for `SEED` and inspect
[`python/services/api/app/mock_data.py`](../python/services/api/app/mock_data.py)
or
[`MockData.cs`](../dotnet/services/api/AgenticSupportGuide.Api/MockData.cs).
The privacy scanner test in
[`maintenance/tests/test_no_sensitive_content.py`](../maintenance/tests/test_no_sensitive_content.py),
shared by both tracks, enforces that only allow-listed placeholder values
appear anywhere.

### Prompt-injection boundaries

- Free-text user input is length-clipped, nothing more. Filtering obfuscated
  injections is deliberately out of scope; Azure's content filters block the
  direct attacks, and Module 8 measures exactly which.
- Every untrusted block reaches the remote agent inside
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` markers, with those
  markers stripped from the body so the fence cannot be closed early.
- The system-level instructions (in `agent.md`) tell the remote agent
  to treat wrapped blocks as data only.
- The control that actually decides what ships is the validator's
  deterministic checks. They match case-insensitively after curly
  apostrophes are folded to straight ones — typography, not evasion. They
  are **not** robust to obfuscation, and that is out of scope.

**How to verify.** Read
[`python/services/api/app/agents/shared/prompt_blocks.py`](../python/services/api/app/agents/shared/prompt_blocks.py)
or
[`dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/PromptBlocks.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/PromptBlocks.cs).
Run `pytest -k prompt_blocks`, or
`dotnet test --solution dotnet\AgenticSupportGuide.slnx --filter-class "*.PromptBlocksTests"`,
for the covering tests.

### Agent-to-agent trust boundaries

- The three agents exchange typed objects only. Each agent's reply is
  parsed into its typed contract (a Pydantic model in Python, a record in
  `Contracts.cs` in .NET) before the next step sees it, and a reply that
  does not parse stops the run.
- The Support Recommendation Agent receives the Data Analyst output
  wrapped as an untrusted block, not injected as instructions.
- The Validator Agent receives both prior outputs the same way.
- Validator repair guidance sent back to the recommender is drawn
  from fixed templates keyed by issue code — not from raw LLM
  critique text.

**How to verify.** Read `parse_role_response` in
[`python/services/api/app/agents/shared/responses.py`](../python/services/api/app/agents/shared/responses.py)
and `_call_agent` in
[`python/services/api/app/workflows/executors.py`](../python/services/api/app/workflows/executors.py);
in .NET, `Responses.ParseRoleResponse` in
[`Responses.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Responses.cs)
and `Nodes.CallAgentAsync` in
[`Executors.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Executors.cs).

### Keyless auth

- The Foundry SDK client acquires bearer tokens through
  `DefaultAzureCredential`, which uses `az login`, managed identity,
  or workload identity. No API key is stored. The .NET track's credential,
  in
  [`Credentials.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Credentials.cs),
  leaves out the Visual Studio and VS Code sign-ins, so both tracks call
  Azure as the same identity.
- Terraform sets `local_auth_enabled = false` on the AI Services
  account and never reads model keys. No key is written to Key Vault.

**How to verify.** Read
[`python/services/api/app/foundry_agents/maf_client.py`](../python/services/api/app/foundry_agents/maf_client.py)
or
[`dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs)
and your track's `ai_foundry.tf` —
[`python/infra/ai_foundry.tf`](../python/infra/ai_foundry.tf) or
[`dotnet/infra/ai_foundry.tf`](../dotnet/infra/ai_foundry.tf) (the
`local_auth_enabled` setting on the `azurerm_cognitive_account`
resource).

### RBAC

Each track's `rbac.tf` (`python/infra/rbac.tf`, `dotnet/infra/rbac.tf`)
creates the same eleven role assignments. They fall into three groups.

The learner (or the `principal_id` passed through `terraform.tfvars`):

| Role | Scope |
| --- | --- |
| `Cognitive Services OpenAI User` | AI Services account |
| `var.project_role_definition_name` | Foundry project |
| `Search Service Contributor` | Search service |
| `Search Index Data Contributor` | Search service |
| `Storage Blob Data Contributor` | Storage account |

The deployed API's managed identity:

| Role | Scope |
| --- | --- |
| `Cognitive Services OpenAI User` | AI Services account |
| `var.project_role_definition_name` | Foundry project |
| `Search Index Data Reader` | Search service |

Service-to-service identities:

| Role | Scope | Why |
| --- | --- | --- |
| `Storage Blob Data Reader` | Storage account | Search reads the knowledge container |
| `Search Index Data Reader` | Search service | AI Services reads the index |
| `Cognitive Services OpenAI User` | AI Services account | Search calls the embedding model |

`Search Service Contributor` is service-wide. A holder can delete any
index on the service, so index names do not provide isolation between
learners who share one. Set `grant_search_control_plane = false` to
withhold it; Module 6 then requires an index created for you.

**How to verify.** Search for `azurerm_role_assignment` in
[`python/infra`](../python/infra) or [`dotnet/infra`](../dotnet/infra).

### No prompt / completion logging

- Telemetry captures structural metadata only: span name, executor id,
  duration, model, token counts, coarse error type.
- Spans come from Agent Framework, whose sensitive-data setting defaults to
  off in both tracks: this app never calls `enable_sensitive_telemetry()`
  in Python and never turns on `EnableSensitiveData` in .NET. A canary
  test in each track asserts no user text reaches a span.
- The audit endpoint returns seeded synthetic rows plus in-memory
  metadata rows and never surfaces prompts, completions, raw
  concern text, or secrets.

**How to verify.** Read
[`python/services/api/app/observability.py`](../python/services/api/app/observability.py)
and
[`python/services/api/app/runtime_audit.py`](../python/services/api/app/runtime_audit.py),
or
[`Observability.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Observability.cs)
and
[`Audit.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Audit.cs).
See [Observability](observability.md) for the safe schema, and for how a
failed call is recorded differently by the two frameworks.

### Metadata-only observability

- See the dedicated [Observability](observability.md) doc.
- `/api/health/details` reports posture flags but never includes the
  configured endpoint URL, deployment name, connection string, or
  token.

**How to verify.** Inspect
[`python/services/api/app/diagnostics.py`](../python/services/api/app/diagnostics.py)
and the test at
[`python/services/api/tests/test_health_details.py`](../python/services/api/tests/test_health_details.py)
that plants canary values in settings and asserts they never appear
in the response body — or, in .NET,
[`Diagnostics.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Diagnostics.cs)
and
[`HealthDetailsTests.cs`](../dotnet/services/api/AgenticSupportGuide.Api.Tests/HealthDetailsTests.cs).

### Human review

- Every recommendation returned to the UI contains a "human review is
  required" caveat, enforced deterministically by the Validator Agent.
- The UI shows a persistent prototype banner and a demo scope
  disclaimer.
- The prototype does not make final pricing, financing, credit,
  compliance, safety, or individual staffing determinations.

**How to verify.** Read the caveat checks in the Validator Agent and
the persistent banner in the frontend layout.

## Secret handling

- `.env`, `terraform.tfvars`, and `*.tfstate` are gitignored.
- `apps/web/.env.example`, `python/services/api/.env.example`, and each
  track's `infra/terraform.tfvars.example` contain placeholder values
  only. The .NET track has no `.env.example`;
  `dotnet/scripts/populate-env.ps1` writes its `.env` from Terraform
  outputs.
- Application Insights connection string is marked `sensitive = true`
  in Terraform outputs.
- The privacy scanner test flags 32+ character base64/hex values on
  lines beginning with `AZURE_*=`.

## Validation gates

- Every remote-agent response is parsed and validated against a typed
  internal contract (Pydantic in Python, `Contracts.cs` in .NET) before it
  is used.
- If validation still fails after one repair pass, no recommendation
  is returned; the API returns a typed `validation_failed` envelope
  with safe issue codes.

## Content-filter handling

- The Foundry adapter classifies content-filter responses (by the error's
  type name or its `content_filter` code) and raises
  `ContentFilterError("CONTENT_FILTER", ...)` —
  `ContentFilterException("CONTENT_FILTER", ...)` in .NET.
- The coordinator maps that to a `provider_content_filter` status
  code and returns a safe user-facing message.
- The UI shows a distinct safe state for content-filter blocks with
  no raw model text.

## Common mistakes to avoid

- Adding a "just for debugging" logger that prints the outgoing
  prompt or the model response. Agent Framework keeps such fields out of
  spans, but there is no filter for a developer-added `print()`.
- Removing the fence around untrusted blocks, or letting a body keep its
  delimiter tags. The fence is what lets the instructions say "treat this as
  data"; a body that can close it early writes outside it.

## What the prototype is not

- Not a real AI-safety review pipeline.
- Not a substitute for human review.
- Not a pricing, credit, safety, staffing, or compliance
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
  the local backend (uvicorn, or `dotnet watch` in the .NET track),
  mirroring production, and the API only insists on a key when it detects
  App Service.

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
account. The limit lives in the proxy rather than the API so that a
caller holding the shared key is not throttled by a limit meant for the
anonymous front door.

It is per instance and in memory, so it resets on restart and would
multiply if the app scaled out. It is a cost guard, not a security
boundary. `model_capacity` and a budget alert remain the backstop.

### What was removed, and why

An earlier version used App Service Easy Auth with per-user Entra
sign-in and dealer group assignments keyed on object id. It was removed
because each learner deploys their own stack: the deploying learner was
the only legitimate user, so per-user identity added a sign-in flow, an
app registration, and several failure modes while defending against a
threat that did not exist.

The cost is real and worth stating plainly: **dealer group isolation is now
a demonstrated pattern, not an enforced control.** The UI picks a
dealer group and the API validates that it exists. Nothing answers "is this
caller allowed that dealer group", because there is no caller identity to
ask about. Retrieval filtering, cross-dealer group citation checks and the
validator's dealer group assertions all still run - they keep a *request*
inside one dealer group, which is what the workshop is teaching.

## Dealer group isolation

Every request carries a `dealer_group_id` matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$`, and the roster is served to the UI from
`/api/supports/options` so no dealer group name is hardcoded in the bundle.
It is enforced at four layers:

- **HTTP** - required by `SupportPlanRequest`.
- **Contracts** - required on every typed agent output and citation.
- **Coordinator** - propagated to every agent context.
- **Validator Agent** - deterministic checks
  (`DRAFT_DEALER_GROUP_MISMATCH`, `CROSS_DEALER_GROUP_CITATION`,
  `UNKNOWN_CITATION_ID`) reject any drift.

These keep evidence for one request inside one dealer group. None of them is
an authorization check, and with no caller identity there is nothing to
authorize against - see above.

### Known gap: the synthetic roster is not dealer group-scoped

`Dealership`, `AreaScoreRecord` and `OperationsRecord` carry no
`dealer_group_id`. Every caller sees the same synthetic network from
`/api/dealerships`, `/api/dashboard/summary`, `/api/scores/summary`,
`/api/operations/summary` and `/api/supports/options`.

This is a property of the mock dataset, not of the request pipeline. A
real deployment must add `dealer_group_id` to these records and filter on
it, exactly as the evidence layer already does for citations.

The target production topology gives each dealer group its own Microsoft
Fabric workspace and lakehouse. This repo ships only synthetic
per-dealer group fixtures via `FixtureEvidenceRetriever`. See
[`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md).

## Human review

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

Transitions:

- Are made through `POST /api/supports/plans/{plan_id}/review`.
- Are validated against the state machine; invalid transitions raise
  `InvalidReviewTransitionError` (`InvalidReviewTransitionException` in
  .NET), returned as HTTP 409.
- Are recorded in the runtime audit log as `review_transition` events
  with `correlation_id`, `dealer_group_id`, old state, new state, and a
  reviewer identifier. No prompt or completion text is stored.

Approval is terminal in the demo. Production would layer on dealer group
approver identity, signing, and workflow escalation. That is out of
scope for this prototype.

## Evidence-backed output

Every passing recommendation attaches at least one citation. The
Validator Agent rejects `MISSING_CITATIONS`,
`CROSS_DEALER_GROUP_CITATION`, and `UNKNOWN_CITATION_ID`. The
`Citation` type includes only safe fields (`citation_id`,
`dealer_group_id`, `source_type`, `source_title`, `section_or_page`,
`evidence_summary`, `source_ref`, `retrieved_at`, `confidence`).
It never carries a raw document body.

See [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md).

## Correlation IDs and safe audit

The coordinator generates a `correlation_id` per request. Audit rows
carry `correlation_id`, `dealer_group_id`, `evidence_count`,
`citation_count`, and `validator_status`. None of them contain
prompts, completions, thread IDs, or run IDs. See
[`observability.md`](observability.md).
