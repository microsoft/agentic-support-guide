# GenAIOps

This document describes how prompts, agent specs, model deployments,
evaluations, and observability are versioned and governed in this
prototype. All examples use synthetic data.

## Source of truth

| Concern | Source of truth |
| --- | --- |
| Human-readable agent instructions | `/agents/<name>/agent.md` |
| Runtime metadata (model, timeouts, contract refs, safety) | `/agents/<name>/manifest.yaml` |
| Inter-agent message contracts | `/contracts/v1/*.schema.json` |
| Agent-local input/output shapes | `/agents/<name>/schemas/*.schema.json` |
| Azure AI Foundry model deployment | Terraform outputs (`ai_services_endpoint`, `model_deployment_name`, `foundry_project_name`) |
| Backend environment binding | `services/api/.env` (never committed) |

## Prompt / spec versioning

- Every `agent.md` and `manifest.yaml` carries a semver `version`.
- Breaking prompt or contract changes (e.g. removing a required field,
  changing a required tier framing) bump the major version.
- Additive changes (a new optional field, an added enum value the
  consumers already tolerate) bump minor/patch.
- The privacy scanner and the spec tests
  ([`services/api/tests/test_agent_specs.py`](../services/api/tests/test_agent_specs.py))
  fail the build if a required section, required YAML field, or
  handoff-contract shape regresses.

## Model deployment configuration

- The model deployment name is chosen at Terraform-apply time via
  `model_deployment_name` in [`infra/terraform.tfvars.example`](../infra/terraform.tfvars.example).
- The backend reads the deployment name via
  `AZURE_AI_FOUNDRY_DEPLOYMENT` at runtime. It never hard-codes the
  deployment.
- Model retirement and lifecycle are documented in
  [`infra/README.md`](../infra/README.md) and in the
  [Azure OpenAI model retirement schedule](https://learn.microsoft.com/azure/ai-services/openai/concepts/model-retirements).
  The default `gpt-4.1-mini` (`2025-04-14`) auto-upgrades on Standard /
  DataZoneStandard SKUs at base-model retirement.

## Evaluation datasets

- All evaluation cases are **synthetic**. See
  [`evals/synthetic_cases.jsonl`](../evals/synthetic_cases.jsonl) for
  the current set.
- Each case describes a synthetic learner and category and lists the
  structural or safety checks that MUST hold on the produced
  recommendation. It does NOT lock down exact model prose.
- Cases and check definitions carry `schema_version` so runs can be
  compared across time.

## Expected structural output

Every LLM call in the runtime asks for `response_format=json_object` and
validates the response against the corresponding contract in
`/contracts/v1/`. Failure to validate is a coordinator-level typed
error, never surfaced content.

## Safety and groundedness checks

Deterministic Python code in `services/api/app/agents/validator/agent.py`
enforces:

- Contract-version compatibility.
- Allowed resource / SMART goal / strategy ID membership.
- Required caveats (must include human-review wording).
- Required support tier framing (`universal`, `targeted`, `intensive`,
  or `enrichment`).
- Required progress-monitoring measures and educator next steps.

The optional LLM critique may **add** advisory warning codes but never
flips a deterministic pass to a failure. Free-text critique is stripped
by `enforce_code()` in
[`services/api/app/agents/shared/sanitization.py`](../services/api/app/agents/shared/sanitization.py).

## Human review

Every recommendation returned to the UI includes explicit human-review
caveats. The prototype cannot make final educational, legal, compliance,
medical, disability, or placement determinations, and the UI's
persistent banner and Demo Guide say so.

## Metadata-only observability

See [`observability.md`](observability.md). The runtime never logs
prompts, completions, raw concern text, raw validator critique, or
secrets. `TelemetryRecorder` has a hard denylist of unsafe keys.

## Comparing prompt / agent versions over time

- `agent.md` and `manifest.yaml` diffs are the primary review artifact.
  Each PR that touches them should include:
  - the reason for the change,
  - which structural or safety checks in `/evals/expected_checks.yaml`
    validate the change,
  - a run of `evals/README.md` steps against the new version.
- Trace metadata already carries `spec_version` (per agent), so
  Application Insights queries can bucket outcomes by version.

## What GenAIOps looks like beyond this prototype

- CI-driven eval runs with reproducible seeds and per-version leaderboards.
- Foundry hosted-agent registry mirroring `/agents/`.
- Automatic promotion gates: unit tests + eval structural checks +
  safety checks + a human review sign-off must all pass before a spec
  version is deployed to production.
- Signed and dated audit records tied to the deployed spec version.

None of that is implemented in the demo. The scaffolding (`/agents`,
`/contracts`, `/evals`, `/scripts/sync_foundry_agents.py`) is the
starting point.
