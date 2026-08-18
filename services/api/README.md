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
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

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

| Variable | Purpose |
| --- | --- |
| `AZURE_AI_FOUNDRY_ENDPOINT` | AI Services endpoint used for chat completion calls. |
| `AZURE_AI_FOUNDRY_PROJECT_NAME` | Azure AI Foundry project name (observability today; SDK routing later). |
| `AZURE_AI_FOUNDRY_DEPLOYMENT` | Model deployment name to invoke. |
| `AZURE_AI_FOUNDRY_API_VERSION` | Azure OpenAI API version. Defaults to `2024-10-21`. |
| `AZURE_AI_FOUNDRY_AUTH_MODE` | `entra` (default). API-key auth is not supported by this build. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional. Empty = telemetry no-ops. |
| `DEMO_RESET_ENABLED` | Development-only. `true` enables `POST /api/demo/reset`. Default `false`. |

## Azure provider behavior

- `AzureFoundryLlmProvider` uses `DefaultAzureCredential` with the
  bearer scope `https://cognitiveservices.azure.com/.default`.
- Requires the `Cognitive Services OpenAI User` role at the AI Services
  account scope (assigned by Terraform).
- Requests structured JSON via `response_format={"type":"json_object"}`.
- Bounded retries with jittered backoff on 429/5xx (max 3 attempts).
- Per-agent timeout is 30 seconds; orchestration budget is 90 seconds.

## Failure modes

| Status | Meaning |
| --- | --- |
| `ok` | Recommendation returned and validated. |
| `provider_missing` | Azure AI Foundry env vars missing. Populate `.env` from Terraform outputs and restart. |
| `provider_timeout` | Provider timed out. |
| `provider_throttling` | Provider throttled after retry budget. |
| `provider_content_filter` | Content-safety block. |
| `provider_error` | Generic provider failure. |
| `invalid_model_json` | Model returned invalid or off-schema JSON. |
| `validation_failed` | Validator failed after one repair pass. No recommendation returned. |
| `orchestration_budget_exhausted` | Coordinator hit the 90 s budget. |

## Endpoints

- `GET  /api/health`
- `GET  /api/health/details`
- `POST /api/demo/reset` (guarded by `DEMO_RESET_ENABLED=true`)
- `GET  /api/dashboard/summary`
- `GET  /api/learners`
- `GET  /api/assessments/summary`
- `GET  /api/behavior/summary`
- `GET  /api/supports/options`
- `POST /api/recommendations/support-plan`
- `GET  /api/supports/plans`
- `POST /api/supports/plans`
- `GET  /api/audit/events`

## Privacy guardrail

`tests/test_no_sensitive_content.py` runs a rule-based scanner across
tracked source/text files. See
[`docs/security-and-privacy.md`](../../docs/security-and-privacy.md).
