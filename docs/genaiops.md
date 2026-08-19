# GenAIOps

This page explains what GenAIOps is in general, then documents exactly
which practices are implemented in this repo and which are remaining
gaps. All examples use synthetic data.

## What GenAIOps means

### What this means

GenAIOps is the operating discipline for generative-AI workloads. It
extends traditional DevOps and MLOps with practices that address the
specific risks of language-model systems: unstable outputs, silent
prompt drift, prompt-injection surfaces, safety failures, and
telemetry that would otherwise leak sensitive text.

### Why it matters

A generative-AI workload can change behavior without a code change.
A one-line edit to a prompt file, a model version rollover, or a
schema drift can silently alter what the app produces. Without
version control, evaluation, and metadata-only observability, teams
lose the ability to explain, reproduce, or roll back changes.

### How it differs from DevOps and MLOps

- **DevOps** treats code, infrastructure, and configuration as
  versioned artifacts and automates their delivery.
- **MLOps** adds datasets, training runs, model registries, and model
  deployments as first-class artifacts and monitors data/model drift.
- **GenAIOps** adds prompts, agent specs, protocol schemas, evaluation
  cases (structural + safety), and metadata-only trace collection on
  top of both.

### Best-practice pattern

A well-run GenAIOps workflow does most of these:

1. **Version prompts and agent specs** in source control. Every prompt
   change is a reviewable commit.
2. **Version inter-agent protocols/schemas.** Breaking changes bump a
   major version; additions are minor.
3. **Use synthetic eval datasets** so evaluation cannot leak real
   user data.
4. **Evaluate structure and safety, not exact prose.** Score whether
   an output uses allowed IDs, contains required caveats, and matches
   the expected schema — not whether it matches a golden string.
5. **Track model deployment/config changes** the same way you track
   application-code changes.
6. **Capture metadata-only traces.** Never log the prompt, the
   completion, or the raw user text.
7. **Review changes before promotion.** A prompt or model rollover
   goes through the same PR review as a code change.
8. **Maintain a rollback path.** A prompt regression should be
   revertable in one commit; a model deployment should be swappable
   without a code deploy.

## How this repo implements each practice

### 1. Version prompts and agent specs

- Each agent's instructions live in `agent.md` inside its folder under
  [`/agents`](../agents).
- Runtime metadata (agent name, response format, model deployment env
  var, temperature) lives in `manifest.yaml` next to it.
- Both are plain text and are reviewed via normal PR flow.
- The remote assistant on Foundry is regenerated from the on-disk
  files by [`scripts/sync_foundry_agents.py`](../scripts/sync_foundry_agents.py).

**How to verify.** Manual review of
[`agents/data-analyst/agent.md`](../agents/data-analyst/agent.md),
[`agents/data-analyst/manifest.yaml`](../agents/data-analyst/manifest.yaml),
and their counterparts under `support-recommender` and `validator`.
Diffs on those files show up in every PR that changes a prompt.

### 2. Version inter-agent protocols/schemas

- Every inter-agent message shape lives in
  [`/contracts/v1`](../contracts/v1) as a JSON Schema
  (`.schema.json`).
- The path segment (`v1`) is the version boundary. Breaking changes
  move to `/contracts/v2/`.
- The coordinator loads the registry at startup and validates every
  agent response against the corresponding schema. Validation
  failures return a typed `PROTOCOL_VALIDATION_FAILED` error and no
  recommendation is surfaced.

**How to verify.** Read [`services/api/app/contracts_registry.py`](../services/api/app/contracts_registry.py)
and search `_protocol_validate` in
[`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py).

### 3. Use synthetic eval datasets

- Evaluation cases live in [`/evals`](../evals). Every case describes
  a synthetic learner and category and lists the structural or safety
  checks that must hold on the produced recommendation.
- No real user data is used anywhere.

**How to verify.** Manual review of files under
[`/evals`](../evals). This repo does not currently ship an automated
eval runner (see gaps below).

### 4. Evaluate structure and safety, not exact prose

- The Validator Agent runs deterministic Python checks in
  [`services/api/app/agents/validator/agent.py`](../services/api/app/agents/validator/agent.py):
  allowed resource / SMART-goal / strategy IDs, required caveats
  (including a "human review" clause), required support-tier framing
  (`universal`, `targeted`, `intensive`, or `enrichment`), required
  progress-monitoring measures, and contract-version match.
- The LLM critique step may **add** advisory warning codes but cannot
  flip a deterministic pass into a failure. Free-text critique is
  filtered through
  [`enforce_code()`](../services/api/app/agents/shared/sanitization.py),
  which drops anything that is not uppercase snake case of at least
  four characters.

**How to verify.** Read the `validate()` method in
`services/api/app/agents/validator/agent.py` and its unit tests in
[`services/api/tests/test_agents.py`](../services/api/tests/test_agents.py).

### 5. Track model deployment/config changes

- The Foundry project, the AI Services account, and the model
  deployment are provisioned by Terraform in [`/infra`](../infra) with
  a pinned `.terraform.lock.hcl`.
- The model deployment name is not hard-coded. The backend reads it
  per role from `FOUNDRY_MODEL_DEPLOYMENT_ANALYST`,
  `FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER`, and
  `FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR` in `services/api/.env`.
- The role-to-assistant mapping (and an `instructions_hash` for drift
  detection) lives in `.foundry/agent-bindings.local.json`, produced
  by `scripts/sync_foundry_agents.py --apply`.

**How to verify.** `terraform state list` in `/infra`; open
`services/api/.env.example`; run
`python scripts/sync_foundry_agents.py --dry-run` from the repo root
— it prints the planned actions per role with no network I/O.

### 6. Capture metadata-only traces

- Telemetry never carries prompts, completions, raw concern text, or
  secrets. See [Observability](observability.md) for the safe schema.
- `TelemetryRecorder` has a hard denylist of unsafe keys
  (`prompt`, `completion`, `concern_text`, `raw_critique`, `secret`,
  `api_key`, `token`).
- The audit trail exposed by `/api/audit/events` mirrors the same
  schema.

**How to verify.** Read
[`services/api/app/telemetry.py`](../services/api/app/telemetry.py)
and
[`services/api/app/runtime_audit.py`](../services/api/app/runtime_audit.py).
The privacy scanner test in
[`services/api/tests/test_no_sensitive_content.py`](../services/api/tests/test_no_sensitive_content.py)
also asserts the repo does not leak canary values.

### 7. Review changes before promotion

- All prompt, contract, Terraform, and code changes go through source
  control PR review.
- A remote agent is only updated by running
  `scripts/sync_foundry_agents.py --apply`. That command is not run
  automatically anywhere in this repo, so a human is always in the
  loop before a change reaches Foundry.

**How to verify.** Read
[`scripts/sync_foundry_agents.py`](../scripts/sync_foundry_agents.py).
Note the `--dry-run` / `--apply` / `--check-connectivity` / `--rebind`
mode split.

### 8. Maintain a rollback path

- Rolling back a prompt or manifest is a revert commit followed by
  `sync_foundry_agents.py --apply`.
- Rolling back a model deployment change is a Terraform `plan` +
  `apply` on the reverted state.
- Bindings are refused when the `project_endpoint_hash` does not
  match the configured endpoint, unless the operator passes
  `--rebind`. This prevents accidental cross-environment reuse of
  assistant IDs.

**How to verify.** Read the endpoint-hash guard in
[`services/api/app/foundry_agents/adapter.py`](../services/api/app/foundry_agents/adapter.py)
and the `--rebind` block in
[`scripts/sync_foundry_agents.py`](../scripts/sync_foundry_agents.py).

## Health / readiness signal

`GET /api/health/details` reports the demo-readiness posture without
leaking any configured environment values:

- `active_provider` — `azure_foundry_agents` when the project endpoint
  is configured and all three roles have bindings; `unconfigured`
  otherwise.
- `foundry_project_configured` — is the project endpoint set.
- `foundry_agents_bound` — do all three role bindings exist and match
  the current endpoint.
- `service_side_remote_workflow_active` — both of the above.
- `customer_demo_ready` — the same as above.

**How to verify.** `curl.exe -s http://127.0.0.1:8000/api/health/details`
against a running backend.

## Common mistakes to avoid

- Editing `agent.md` and forgetting to run `sync_foundry_agents.py
  --apply`. The remote assistant then serves stale instructions. The
  `instructions_hash` field in the bindings file exists to catch this
  drift on the next `--dry-run`.
- Adding a "just this once" direct model call from the coordinator or
  a role wrapper. The import-graph assertion in
  `tests/test_agents_config.py::test_no_direct_model_calls_outside_sdk_client`
  fails the build if any file outside
  `services/api/app/foundry_agents/sdk_client.py` imports
  `azure.ai.agents`, `AzureOpenAI`, `openai.`, or references
  `chat.completions`.
- Grading eval output by prose. Grade by allowed IDs, required
  caveats, tier framing, and schema conformance.
- Turning on prompt/completion logging in Application Insights "for
  debugging." Extend the metadata-only facade instead; see
  [Observability](observability.md).

## Remaining gaps in this repo

None of the following is implemented and should not be described as
existing:

- **No CI workflow.** Lint, mypy, pytest, ruff, frontend build/test,
  `terraform validate`, and `sync_foundry_agents.py --dry-run` all run
  locally but are not enforced by any pipeline in this repo.
- **No automated eval harness.** The `/evals` folder holds synthetic
  cases and expected checks, but there is no runner that scores an
  agent version against them and blocks promotion.
- **No promotion gate.** A prompt change can be applied to Foundry
  without any eval or safety pass; the guardrail today is human PR
  review.
- **No signed audit records.** The audit trail is metadata-only but
  is not tamper-evident.

These are the concrete places where this prototype would grow toward
a production GenAIOps posture.

## See also

- [`agents-vs-prompts.md`](agents-vs-prompts.md) — why this workload
  is a multi-agent workflow rather than one bigger prompt.
- [`foundry-fabric-deep-dive.md`](foundry-fabric-deep-dive.md) — how
  Foundry and Fabric fit together in the target topology.
- [`adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)
- [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
