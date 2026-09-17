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
- Runtime metadata (response format, model deployment env var,
  temperature) lives in `manifest.yaml` next to it.
- Both are plain text and are reviewed via normal PR flow.
- The runtime composes instructions from these files on every call, so the
  version that runs locally is exactly the version on the branch.
- Publishing the same definitions to Foundry as prompt agents is a separate,
  explicit step (`scripts/publish_prompt_agents.py`), which is what makes
  them visible and versioned in the portal. See
  [ADR 0006](adr/0006-published-prompt-agents.md).

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
and `StepRunner.check_protocol` in
[`services/api/app/workflows/steps.py`](../services/api/app/workflows/steps.py).

### 3. Use synthetic eval datasets

- Evaluation cases live in [`/evals`](../evals). Every case describes
  a synthetic dealership and category and lists the structural or safety
  checks that must hold on the produced recommendation.
- No real user data is used anywhere.

**How to verify.** Run `python scripts/run_evals.py --offline` for the
deterministic structural gate, and `python scripts/run_agent_evals.py
--dry-run` for the graded quality pass. Neither is wired to block a merge
automatically — both are run on demand.

### 4. Evaluate structure and safety, not exact prose

- The Validator Agent runs deterministic Python checks in
  [`services/api/app/agents/validator/agent.py`](../services/api/app/agents/validator/agent.py):
  allowed resource / goal / strategy IDs, required caveats
  (including a "human review" clause), required support-tier framing
  (`baseline`, `focused`, `intensive`, or `advanced`), required
  progress-monitoring measures, and contract-version match.
- The LLM critique step may **add** advisory warning codes but cannot
  flip a deterministic pass into a failure. Free-text critique is
  filtered through
  [`enforce_code()`](../services/api/app/agents/shared/prompt_blocks.py),
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
- The role-to-deployment mapping comes from `manifest.yaml`
  (`foundry.model_deployment_env`) resolved against the environment at
  startup. There is no binding file, because there is no persisted
  agent to bind to.
- `scripts/validate_agent_definitions.py` prints an `instructions_hash`
  per role. A changed hash means the composed instructions changed, which
  is the drift signal that used to live in the bindings file.

**How to verify.** `terraform state list` in `/infra`; open
`services/api/.env.example`; run
`python scripts/validate_agent_definitions.py` from the repo root
— it validates every definition and prints each hash with no network I/O.

### 6. Capture metadata-only traces

- Telemetry never carries prompts, completions, raw concern text, or
  secrets. See [Observability](observability.md) for the safe schema.
- Spans come from Agent Framework, whose `enable_sensitive_data` setting
  defaults to False; this app never opts in.
- The audit trail exposed by `/api/audit/events` mirrors the same
  schema.

**How to verify.** Read
[`services/api/app/observability.py`](../services/api/app/observability.py)
and
[`services/api/app/runtime_audit.py`](../services/api/app/runtime_audit.py).
The privacy scanner test in
[`services/api/tests/test_no_sensitive_content.py`](../services/api/tests/test_no_sensitive_content.py)
also asserts the repo does not leak canary values.

### 7. Review changes before promotion

- All prompt, contract, Terraform, and code changes go through source
  control PR review.
- The locally running instructions are always the ones on the branch,
  composed per call. Promotion of the *running* app is just merging.
- The **published** prompt agents are a separate artifact and can drift
  from the branch. Re-run
  `python scripts/publish_prompt_agents.py --suffix <you> --apply` after
  merging a prompt change, and compare the `instructions_hash` from
  `validate_agent_definitions.py` against the version you published.
- CI runs `scripts/validate_agent_definitions.py` on every pull request,
  so a malformed definition or a stale contract reference fails before
  merge.

**How to verify.** Read the `agent-definitions` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) and
[`scripts/validate_agent_definitions.py`](../scripts/validate_agent_definitions.py).

### 8. Maintain a rollback path

- Rolling back a prompt or manifest is a **revert commit**. Because
  instructions are composed per call, the running app reverts as soon as
  the reverted code is running.
- If you had published that prompt, also re-publish after reverting.
  Prompt agents are versioned, so the previous version stays visible in
  the portal and the new version simply supersedes it.
- Rolling back a model deployment change is a Terraform `plan` +
  `apply` on the reverted state.

**How to verify.** Revert a change to any `agents/*/agent.md`, restart
the backend, and confirm the `instructions_hash` reported by
[`scripts/validate_agent_definitions.py`](../scripts/validate_agent_definitions.py)
returns to its previous value.

## Health / readiness signal

`GET /api/health/details` reports the demo-readiness posture without
leaking any configured environment values:

- `active_provider` — `azure_foundry_responses` when the project endpoint
  is configured, all three agent definitions load, and their model
  deployments are set; `unconfigured` otherwise.
- `foundry_project_configured` — is the project endpoint set.
- `agent_definitions_valid` — did all three role definitions load from
  `/agents`.
- `model_deployments_configured` — are all three
  `FOUNDRY_MODEL_DEPLOYMENT_*` variables set.
- `service_side_remote_workflow_active` — all of the above.
- `customer_demo_ready` — the same as above.

All of these are local checks. The frontend polls this endpoint on every
page load, so it deliberately makes no network call to Azure. Use
`python scripts/validate_agent_definitions.py --check-connectivity` for
the live check.

**How to verify.** `curl.exe -s http://127.0.0.1:8000/api/health/details`
against a running backend.

## Common mistakes to avoid

- Calling `to_prompt_agent` or `agents.create_version` from application
  code. Publishing is a GenAIOps step, allowlisted to
  `scripts/publish_prompt_agents.py`; a web request must never publish an
  agent. `tests/test_no_persisted_agents.py` fails the build if those
  symbols appear anywhere else.
- Publishing without `--suffix`. The script refuses, because dozens of
  learners share one subscription and unsuffixed names collide.
- Adding a "just this once" direct model call from the coordinator or
  a role wrapper. All Agent Framework SDK imports belong in
  `services/api/app/foundry_agents/maf_client.py`.
- Renaming the provider identifier in Python only. It is also written
  into YAML manifests, TypeScript, PowerShell, and Markdown, which
  cannot import a Python constant.
  `tests/test_provider_vocabulary.py` greps those files for stale terms.
- Grading eval output by prose. Grade by allowed IDs, required
  caveats, tier framing, and schema conformance.
- Turning on prompt/completion logging in Application Insights "for
  debugging." Extend the metadata-only facade instead; see
  [Observability](observability.md).

## Remaining gaps in this repo

None of the following is implemented and should not be described as
existing:

- **No promotion gate.** A prompt change can be applied to Foundry
  without any eval or safety pass; the guardrail today is human PR
  review plus the CI checks in
  [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). CI runs
  `run_evals.py --offline` against fixtures, but nothing blocks a merge on a
  live-model score.
- **No signed audit records.** The audit trail is metadata-only but
  is not tamper-evident.

These are the concrete places where this prototype would grow toward
a production GenAIOps posture.

## See also

- [`agents-vs-prompts.md`](agents-vs-prompts.md) — why this workload
  is a multi-agent workflow rather than one bigger prompt.
- [`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md)
- [`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
