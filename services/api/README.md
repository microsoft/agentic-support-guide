# Backend - agentic-support-guide API

Local prototype FastAPI service that hosts three collaborating agents
backed by Azure AI Foundry model deployments.

- Data Analyst Agent
- Support Recommendation Agent
- Validator Agent

The FastAPI app mounts every route under `/api`. OpenAPI is at
`/api/openapi.json` and the docs UI is at `/api/docs`.

## Requirements

- Python 3.12+ (3.13 is used in local development).
- `az` CLI logged in for `DefaultAzureCredential`.

## Setup

```powershell
cd services/api
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Populate `.env` with the Terraform outputs (see the infra README).

## Run

```powershell
az login
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --env-file .env
```

`--env-file .env` is required: `load_foundry_settings()` reads the process
environment and nothing in the app loads `.env` implicitly.

- OpenAPI: http://127.0.0.1:8000/api/openapi.json
- Docs UI: http://127.0.0.1:8000/api/docs

## Quality checks

```powershell
ruff format --check .
ruff check .
mypy .
pytest
```

## Environment variables

Canonical list lives in [`.env.example`](.env.example).

| Variable | Purpose |
| --- | --- |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint (`https://<resource>.services.ai.azure.com/api/projects/<project>`). Required. `AZURE_AI_FOUNDRY_ENDPOINT` is accepted as a fallback name. |
| `FOUNDRY_MODEL_DEPLOYMENT_ANALYST` | Model deployment backing the Data Analyst agent. Read by `scripts/validate_agent_definitions.py`. |
| `FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER` | Model deployment backing the Support Recommendation agent. |
| `FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR` | Model deployment backing the Validator agent. |
| `AZURE_AI_FOUNDRY_AUTH_MODE` | `entra` (default). API-key auth is not supported by this build. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional. Empty = telemetry no-ops. |
| `DEMO_RESET_ENABLED` | Development-only. `true` enables `POST /api/demo/reset`. Default `false`. |

There are no remote assistant IDs. Each role is assembled in-process from
`agents/<id>/agent.md` on every call.

## Azure provider behavior

- `FoundryResponsesClientFactory` (`app/foundry_agents/maf_client.py`) is
  the only module importing Agent Framework. It builds an
  `agent_framework.Agent` on a `FoundryChatClient` per call, with
  `store=False` and a `response_format` bound to the role's contract.
- `MafAgentRuntime` (`app/foundry_agents/maf_runtime.py`) resolves a role
  to its definition and enforces the per-run timeout. Agents are
  ephemeral: nothing is created or stored in Foundry.
- Requires the `Cognitive Services OpenAI User` role at the AI Services
  account scope (assigned by Terraform).
- Per-run timeout is 30 seconds (`FOUNDRY_RUN_TIMEOUT_SECONDS`); the whole
  workflow budget is 120 seconds (`ORCHESTRATION_TOTAL_BUDGET_SECONDS`).
  Each run's timeout is clamped to whatever is left of that budget.
- There is no client-side retry. Throttling surfaces as `ThrottledError`
  and is reported to the caller as `provider_throttling`.

## Failure modes

| Status | Meaning |
| --- | --- |
| `ok` | Recommendation returned and validated. |
| `provider_missing` | Project endpoint or per-role model deployments missing. Run `.\scripts\populate-env.ps1`, then restart with `--env-file .env`. |
| `provider_timeout` | Provider timed out. |
| `provider_throttling` | Provider throttled the request. |
| `provider_content_filter` | Content-safety block. |
| `provider_error` | Generic provider failure. |
| `evidence_missing` | Dealer-group-scoped evidence retrieval returned nothing usable. |
| `invalid_model_json` | Model returned invalid or off-schema JSON. |
| `validation_failed` | Validator failed after one repair pass. No recommendation returned. |
| `orchestration_budget_exhausted` | Coordinator hit the 120 s budget. |

## Endpoints

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

`tests/test_no_sensitive_content.py` runs a rule-based scanner across
tracked source/text files. See
[`docs/security-and-privacy.md`](../../docs/security-and-privacy.md).
