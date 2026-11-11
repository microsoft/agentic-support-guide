# Backend - agentic-support-guide API (.NET)

Local prototype ASP.NET Core service that hosts three collaborating agents
backed by Microsoft Foundry model deployments. It is the .NET track's copy of
the API the Python track serves from
[`python/services/api`](../../../python/services/api/README.md): the same
routes, request and response bodies, status codes and agent behaviour, checked
against recordings of the Python app by the
[conformance tests](../../../conformance/README.md).

- Data Analyst Agent
- Support Recommendation Agent
- Validator Agent

[`Endpoints.cs`](AgenticSupportGuide.Api/Endpoints.cs) maps every route under
`/api`. On a local run, OpenAPI is at `/api/openapi.json` and the Swagger UI
is at `/api/docs`; both are off on App Service.

## Requirements

- .NET 10 SDK, 10.0.404 or a later 10.0 SDK. The repo's
  [`global.json`](../../../global.json) pins that band and the
  Microsoft.Testing.Platform test runner, so run every `dotnet` command from
  inside the repo.
- `az` CLI logged in for `DefaultAzureCredential`. The app's credential, in
  [`Credentials.cs`](AgenticSupportGuide.Api/Credentials.cs), leaves out the
  Visual Studio and VS Code sign-ins, so on a laptop it resolves to your
  `az login` account, as the Python track does.

## Setup

From the repo root:

```powershell
dotnet build dotnet/AgenticSupportGuide.slnx
.\dotnet\scripts\populate-env.ps1
```

`populate-env.ps1` writes `dotnet/services/api/.env` from the Terraform
outputs (see the [infra README](../../infra/README.md)). This track has no
`.env.example`; [Environment variables](#environment-variables) lists the keys.

The build copies the shared agent definitions from the repo root's `agents/`
folder next to the app, which reads them from there. The build output is
self-contained, and an edit to `agent.md` takes effect on the next build and
restart.

## Run

From the repo root:

```powershell
az login
.\dotnet\scripts\run-backend.ps1
```

`run-backend.ps1` is required in the way `--env-file .env` is in the Python
track: `AzureFoundrySettings.Load()` in
[`Config.cs`](AgenticSupportGuide.Api/Config.cs) reads the process
environment, and nothing in the app loads `.env`. The script:

- loads `dotnet/services/api/.env` into the backend process only. A variable
  already set in your shell wins, and nothing is left behind in the shell when
  the backend stops, so blanking a line in `.env` and restarting unsets it;
- sets `ASPNETCORE_URLS=http://127.0.0.1:8000`, where the Vite dev server
  proxies `/api`;
- runs the API under `dotnet watch`, so a saved change rebuilds and restarts
  it;
- builds into `AgenticSupportGuide.Api\obj\watch` instead of `bin\`, because
  the running app locks the files it was built to. `dotnet test` and IDE
  builds keep working while the backend runs.

- OpenAPI: http://127.0.0.1:8000/api/openapi.json
- Swagger UI: http://127.0.0.1:8000/api/docs

## Quality checks

From the repo root:

```powershell
dotnet format whitespace dotnet/AgenticSupportGuide.slnx --verify-no-changes
dotnet build dotnet/AgenticSupportGuide.slnx
dotnet test --solution dotnet/AgenticSupportGuide.slnx
dotnet run dotnet/scripts/validate_agent_definitions.cs
```

Warnings are errors in this track
([`Directory.Build.props`](../../Directory.Build.props)), so the build is also
the lint and the type check.

The tests in [`AgenticSupportGuide.Api.Tests`](AgenticSupportGuide.Api.Tests)
are xUnit v3 on Microsoft.Testing.Platform. They port the Python suite file
for file — `tests/test_x_y.py` becomes `XYTests.cs`, and
`test_some_behaviour` becomes `Some_behaviour` — and add the conformance
replay in [`Conformance/`](AgenticSupportGuide.Api.Tests/Conformance). Run one
class with `--filter-class`:

```powershell
dotnet test --solution dotnet/AgenticSupportGuide.slnx --filter-class "*.ObservabilityTests"
```

[`.github/workflows/ci-dotnet.yml`](../../../.github/workflows/ci-dotnet.yml)
runs the same checks on every pull request, without installing Python.

## Environment variables

There is no `.env.example` in this track. The canonical list is what
[`populate-env.ps1`](../../scripts/populate-env.ps1) writes, and every name is
the same as in the Python track.

| Variable | Purpose |
| --- | --- |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint (`https://<resource>.services.ai.azure.com/api/projects/<project>`). Required. `AZURE_AI_FOUNDRY_ENDPOINT` is accepted as a fallback name. |
| `FOUNDRY_MODEL_DEPLOYMENT_ANALYST` | Model deployment backing the Data Analyst agent. Read by `dotnet/scripts/validate_agent_definitions.cs`. |
| `FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER` | Model deployment backing the Support Recommendation agent. |
| `FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR` | Model deployment backing the Validator agent. |
| `AZURE_AI_FOUNDRY_AUTH_MODE` | `entra` (default). API-key auth is not supported by this build. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional. Empty = telemetry no-ops. |
| `DEMO_RESET_ENABLED` | Development-only. `true` enables `POST /api/demo/reset`. Default `false`. |
| `EVIDENCE_SOURCE` | `fixtures` (default) or `foundry_iq`. Module 6 switches it, with `AZURE_SEARCH_ENDPOINT`, `FOUNDRY_IQ_KNOWLEDGE_BASE` and `FOUNDRY_IQ_KNOWLEDGE_SOURCE`. |
| `ASPNETCORE_URLS` | Where the app listens. `run-backend.ps1` sets `http://127.0.0.1:8000`; on App Service, Terraform sets `http://0.0.0.0:8000`. |

`populate-env.ps1` also writes the keys the workshop scripts read:
`FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER`, `FOUNDRY_MODEL_DEPLOYMENT_ROUTER`,
`FOUNDRY_MODEL_DEPLOYMENT_JUDGE`, `KNOWLEDGE_STORAGE_ACCOUNT`,
`KNOWLEDGE_CONTAINER` and `WORKSHOP_LEARNER_SUFFIX`. It keeps an existing
suffix when it regenerates the file. The scripts load `.env` themselves, and a
variable already set in your shell wins.

There are no stored agent IDs to bind to. Each role's instructions are loaded
from `agents/<id>/agent.md` once at startup and cached; a fresh Agent
Framework agent is built per call from that cached text.

## Azure provider behavior

- `FoundryResponsesClientFactory`
  ([`FoundryAgents/MafClient.cs`](AgenticSupportGuide.Api/FoundryAgents/MafClient.cs))
  is the only type that uses the Agent Framework *model client*. It builds an
  Agent Framework agent per call from the project client
  (`AIProjectClient.AsAIAgent`), with response storage off
  (`StoredOutputEnabled = false`) and a strict JSON-schema response format
  taken from the agent folder's `schemas/output.schema.json`. Agent
  Framework's workflow API is used in three other files:
  [`Workflows/Graph.cs`](AgenticSupportGuide.Api/Workflows/Graph.cs)
  (`WorkflowBuilder`),
  [`Workflows/Executors.cs`](AgenticSupportGuide.Api/Workflows/Executors.cs)
  (the `Executor<PlanState>` nodes) and
  [`Workflows/Coordinator.cs`](AgenticSupportGuide.Api/Workflows/Coordinator.cs)
  (`InProcessExecution` and the workflow's event stream).
  [`Observability.cs`](AgenticSupportGuide.Api/Observability.cs) only exports
  what Agent Framework emits; `WithOpenTelemetry` in `Graph.cs` and
  `UseOpenTelemetry` in `MafClient.cs` switch the instrumentation on.
- `MafAgentRuntime`
  ([`FoundryAgents/MafRuntime.cs`](AgenticSupportGuide.Api/FoundryAgents/MafRuntime.cs))
  resolves a role to its definition and maps provider errors to typed
  failures. Agents are ephemeral: nothing is created or stored in Foundry.
- Requires the `Cognitive Services OpenAI User` role at the AI Services
  account scope (assigned by Terraform).
- The app sets no timeouts of its own. A model call is bounded by the Foundry
  client's default network timeout, and a request as a whole by App Service's
  230 second front-end limit.
- The Foundry client under Agent Framework (`AIProjectClient`, built on
  System.ClientModel) retries a failed call. `FoundryResponsesClientFactory`
  sets its policy to two retries, the number the Python track's OpenAI client
  makes by default; System.ClientModel's own default is three. A call is
  retried when it cannot connect or gets a 408, 429, 500, 502, 503 or 504,
  waiting 0.8 and then 1.6 seconds, or longer when the response's
  `Retry-After` header asks for it. The Python track's client retries on 408,
  409, 429 and any 5xx, with jittered waits. A 429 that exhausts the retries
  surfaces as `provider_throttling`; a client timeout surfaces as
  `provider_timeout`.

## Failure modes

| Status | Meaning |
| --- | --- |
| `ok` | Recommendation returned and validated. |
| `provider_missing` | Project endpoint or per-role model deployments missing. Run `.\dotnet\scripts\populate-env.ps1`, then restart with `.\dotnet\scripts\run-backend.ps1`. |
| `provider_timeout` | Provider timed out. |
| `provider_throttling` | Provider throttled the request. |
| `provider_content_filter` | Content-safety block. |
| `provider_error` | Generic provider failure. |
| `evidence_missing` | Dealer-group-scoped evidence retrieval returned nothing usable. |
| `invalid_model_json` | Model returned invalid or off-schema JSON. |
| `validation_failed` | Validator failed after one repair pass. No recommendation returned. |
| `orchestration_error` | The workflow produced no single result. |

## Endpoints

The same as the Python track's:

- `GET  /api/health`
- `GET  /api/health/details`
- `POST /api/demo/reset` (guarded by `DEMO_RESET_ENABLED=true`)
- `GET  /api/dashboard/summary`
- `GET  /api/dealerships`
- `GET  /api/scores/summary`
- `GET  /api/operations/summary`
- `GET  /api/supports/options`
- `POST /api/recommendations/support-plan`
- `GET  /api/supports/plans`
- `POST /api/supports/plans`
- `POST /api/supports/plans/{plan_id}/review`
- `GET  /api/audit/events`

## Privacy guardrail

[`maintenance/tests/test_no_sensitive_content.py`](../../../maintenance/tests/test_no_sensitive_content.py)
runs a rule-based scanner across tracked source/text files, this track's
`.cs`, `.csproj` and `.props` files included. It is shared repo tooling
written in Python, so it runs in
[`ci-shared.yml`](../../../.github/workflows/ci-shared.yml) rather than in
this track's CI. See
[`docs/security-and-privacy.md`](../../../docs/security-and-privacy.md).
