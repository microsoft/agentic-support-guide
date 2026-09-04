# Iteration Plan — Evidence, District Grounding, Human Review

Date: 2026-08-19

> **Historical document.** It describes the retired persisted-agent
> design; see [ADR 0005](adr/0005-agent-framework-ephemeral-agents.md)
> for the current one.
>
> **Original note:** This is a point-in-time planning snapshot and is
> not kept current. Counts and file inventories below reflect the repository
> as of the date above. For current state, read the
> [README](../README.md) and [architecture](architecture.md).

This plan captures the current state of the repository against the
requirements of the latest customer alignment call and lists the exact
changes this iteration will make.

## 1. Current-state inventory

### Agents (already implemented)

- Three role folders under [`/agents`](../agents):
  - `data-analyst/` (Data Analyst Agent)
  - `support-recommender/` (Support Recommendation Agent)
  - `validator/` (Validator Agent)
- Each folder has `agent.md` (instructions), `manifest.yaml` (runtime +
  Foundry binding metadata), and `schemas/`.
- Runtime is remote Azure AI Foundry Agent Service via
  [`MafAgentRuntime`](../services/api/app/foundry_agents/maf_runtime.py).

### Foundry integration

- [`services/api/app/foundry_agents/maf_client.py`](../services/api/app/foundry_agents/maf_client.py)
  is the only file that imports `azure.ai.agents`. Enforced by
  `tests/test_agents_config.py::test_no_direct_model_calls_outside_maf_client`.
- Adapter maps SDK failures to typed `FoundryProviderError` subclasses
  (`ConfigurationError`, `AuthError`, `ThrottledError`,
  `ContentFilterError`, `FoundryTimeoutError`, `RequiresActionError`,
  `FoundryRunError`).
- No runtime mock mode. Tests inject `FakeFoundryClient` via DI.

### Contracts

- [`/contracts/v1`](../contracts/v1) holds seven JSON Schemas:
  `data-analysis-request/result`, `support-recommendation-request/result`,
  `validation-request/result`, `agent-trace`.
- Coordinator validates each inter-agent message against the schema and
  emits a typed `PROTOCOL_VALIDATION_FAILED` on failure.
- Internal Pydantic types in
  [`services/api/app/agents/shared/contracts.py`](../services/api/app/agents/shared/contracts.py):
  `AnalysisSummary`, `DataAnalystOutput`, `SupportRecommendationDraft`,
  `ValidatorReport`, `ResourceRef`.

### Docs

- [`architecture.md`](architecture.md), [`architecture-diagram.md`](architecture-diagram.md),
  [`architecture.dsl`](architecture.dsl), [`architecture.svg`](architecture.svg).
- [`getting-started-for-new-teams.md`](getting-started-for-new-teams.md),
  [`glossary.md`](glossary.md).
- [`genaiops.md`](genaiops.md), [`security-and-privacy.md`](security-and-privacy.md),
  [`observability.md`](observability.md).
- ADRs: [`adr/0001-agent-hosting.md`](adr/0001-agent-hosting.md) (superseded),
  [`adr/0002-agent-hosting-remote-foundry.md`](adr/0002-agent-hosting-remote-foundry.md),
  [`adr/0001-foundry-project.md`](adr/0001-foundry-project.md).

### Tests

- 98 backend tests, all passing.
- Ruff format/check, mypy strict all clean.
- Frontend: 9 vitest tests pass.
- Privacy scanner in `services/api/tests/scanner.py` + denylist.

### Audit flow

- `services/api/app/telemetry.py` — `TelemetryRecorder` with denylist of
  unsafe keys (`prompt`, `completion`, `concern_text`, `raw_critique`,
  `secret`, `api_key`, `token`).
- `services/api/app/runtime_audit.py` — in-memory `RuntimeAuditLog`.
- `/api/audit/events` returns seeded synthetic rows + in-memory metadata.
- Coordinator generates a `trace_id` and stamps it on every envelope.

## 2. Gaps against this iteration's requirements

| # | Gap | Required by |
| - | --- | ----------- |
| G1 | No `district_id` anywhere (request, contracts, audit, evidence). | B |
| G2 | No evidence/citation schema; recommendations have `evidence_summary` free-text only. | A |
| G3 | No evidence retrieval abstraction. | C |
| G4 | Validator does not check citations, cross-district evidence, unknown source refs. | D |
| G5 | No human review state model (draft / pending_review / approved / rejected). | E |
| G6 | `correlation_id` not distinct from `trace_id`; audit metadata lacks evidence/citation/validator counts. | F |
| G7 | No `docs/agents-vs-prompts.md`. | G |
| G8 | No `docs/foundry-fabric-deep-dive.md`. | H |
| G9 | Architecture diagram does not show Fabric workspace / evidence retrieval. | I |
| G10 | `/api/health/details` does not report `evidence_fixture_available` or `district_isolation_enabled`. | J |
| G11 | Privacy scanner does not check GUID/tenant-ID/subscription-ID patterns. | K |
| G12 | No ADR for district isolation or grounding. | B, C |

## 3. File-by-file change list

### New files

- `contracts/v1/citation.schema.json` — citation envelope (embedded in recommendation-result).
- `services/api/app/agents/shared/evidence.py` — `Citation`, `EvidenceRequest`, `EvidenceBundle` Pydantic types.
- `services/api/app/evidence/__init__.py`, `retrieval.py`, `fixtures.py` — evidence retrieval abstraction + synthetic fixtures keyed by `district_id`.
- `services/api/app/human_review.py` — review-state enum + audit transitions.
- `services/api/tests/test_evidence_retrieval.py`
- `services/api/tests/test_district_isolation.py`
- `services/api/tests/test_validator_citation_checks.py`
- `services/api/tests/test_human_review_state.py`
- `services/api/tests/test_correlation_id_flow.py`
- `docs/iteration-plan.md` (this file)
- `docs/adr/0003-district-isolation-and-grounding.md`
- `docs/adr/0004-grounding-and-citations.md`
- `docs/agents-vs-prompts.md`
- `docs/foundry-fabric-deep-dive.md`

### Modified files

- `contracts/v1/support-recommendation-request.schema.json` — add `district_id`.
- `contracts/v1/support-recommendation-result.schema.json` — add `citations` + `district_id`.
- `contracts/v1/data-analysis-request.schema.json` — add `district_id`.
- `contracts/v1/data-analysis-result.schema.json` — add `district_id`.
- `contracts/v1/validation-request.schema.json` — add `district_id`.
- `contracts/v1/validation-result.schema.json` — add `failed_fields`, `safe_summary`, `district_id`.
- `services/api/app/agents/shared/contracts.py` — extend Pydantic types with `district_id` and `citations`; add `ValidatorReport.failed_fields` + `safe_summary`.
- `services/api/app/models.py` — `SupportPlanRequest.district_id`, `Recommendation.citations`, `Recommendation.district_id`, `Recommendation.human_review_state`, `RecommendationEnvelope.correlation_id`, `SavedPlan.human_review_state`, `AuditEvent.correlation_id + district_id + evidence_count + citation_count + validator_status`, `HealthDetailsResponse.evidence_fixture_available + district_isolation_enabled`.
- `services/api/app/workflows/coordinator.py` — generate + propagate `correlation_id`, call evidence retrieval, pass `district_id` and citations through each hop.
- `services/api/app/agents/*/agent.py` — accept `district_id`, plumb citations through.
- `services/api/app/agents/validator/agent.py` — add citation checks (missing citations, cross-district refs, unknown source refs), populate `failed_fields` and `safe_summary`.
- `services/api/app/main.py` — plumb `district_id` into `CoordinatorRequest`; expose `correlation_id` on the envelope; add human-review state on save.
- `services/api/app/diagnostics.py` — new booleans.
- `services/api/app/telemetry.py`, `runtime_audit.py` — carry the new safe metadata fields; keep denylist.
- `services/api/app/plans_store.py` — add human-review state field.
- `services/api/tests/scanner.py` — add GUID/subscription/tenant/resource-ID patterns.
- `services/api/tests/conftest.py`, `test_coordinator.py`, `test_endpoints.py`, `test_health_details.py`, `test_agents.py`, `test_validator_hardening.py` — updated fixtures/tests reflecting new fields.
- `apps/web/src/api/types.ts`, `apps/web/src/test/fixtures.ts` — mirror new fields.
- `docs/architecture.md`, `docs/architecture.dsl`, `docs/architecture.svg` — reflect Fabric workspace boundary + evidence retrieval + district isolation + human review.
- `docs/security-and-privacy.md`, `docs/genaiops.md`, `docs/observability.md`, `docs/glossary.md`, `README.md` — link the new docs and describe the new safety fields.

### Not-touched (per non-goals)

- `infra/` — no infrastructure changes.
- `apps/web/src/` beyond `types.ts` and `fixtures.ts` — no UI redesign.
- Runtime never gains a mock mode.

## 4. Risks

- Existing tests reference the current `SupportRecommendationDraft`
  shape. Adding required fields (`district_id`, `citations`) means many
  fixtures need updating in one pass.
- The JSON Schema files use `additionalProperties: false`. Adding
  required fields is a breaking change for anyone consuming v1. Since
  there is no external consumer yet, this is acceptable.
- Coordinator now depends on evidence retrieval. If retrieval fails the
  coordinator must return a typed provider_missing-like error, not fall
  back to no-evidence output.

## 5. Acceptance checklist

- [x] `docs/iteration-plan.md` exists (this file).
- [x] `district_id` required in request, evidence, citations,
      handoffs, audit, and traces (verified by tests).
- [x] `Citation` schema exists and every recommendation carries at
      least one citation, enforced by the Validator.
- [x] Cross-district citations rejected with a typed issue code.
- [x] Synthetic evidence retrieval works and is district-scoped.
- [x] `correlation_id` propagates from HTTP entry through all three
      agent hops, evidence retrieval, audit, and API response.
- [x] Human review state has enumerated values (`draft`,
      `pending_review`, `approved`, `rejected`) with audited transitions.
- [x] `/api/health/details` reports `evidence_fixture_available` and
      `district_isolation_enabled` without leaking env values.
- [x] Validator returns `passed`, `issue_codes`, `warning_codes`,
      `failed_fields`, and `safe_summary`; never raw critique.
- [x] Privacy scanner rejects GUID/tenant/subscription/resource-ID
      patterns.
- [x] `docs/agents-vs-prompts.md`, `docs/foundry-fabric-deep-dive.md`,
      ADR 0003, ADR 0004 all exist.
- [x] Architecture doc + diagram reflect district Fabric boundary,
      evidence retrieval, human review, and audit metadata.
- [x] Full local sweep passes: `ruff format --check`, `ruff check`,
      `mypy`, `pytest`, `npm run build`, `npm run test`.
