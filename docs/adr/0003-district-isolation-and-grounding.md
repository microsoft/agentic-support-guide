# ADR 0003 - District isolation and grounding

Supersedes: none
Status: Accepted
Date: 2026-08-19

## Context

Customer data lives in Microsoft Fabric with a **separate workspace and
lakehouse per district**. Each district's data must stay within that
district: recommendations produced for District A can never surface
data, citations, or documents from District B. This is a hard product
requirement.

The three-agent workflow already existed. What was missing was a
first-class notion of `district_id` across the request, agent
handoffs, evidence retrieval, audit records, and trace metadata.

## Decision

Introduce `district_id` as a **required, contract-level field** at every
layer of the recommendation workflow:

1. **HTTP boundary.** `SupportPlanRequest` requires `district_id`
   matching pattern `^[A-Z0-9][A-Z0-9\-]{1,31}$`.
2. **JSON Schemas.** `district_id` is required in every payload in
   `/contracts/v1/*.schema.json` (request, result, and citation
   payloads).
3. **Pydantic contracts.** `DataAnalystOutput`, `SupportRecommendationDraft`,
   `ValidatorReport`, and `Citation` all require `district_id`.
4. **Coordinator.** `CoordinatorRequest.district_id` is passed into
   every agent context and stamped on every envelope payload.
5. **Validator.** Deterministic checks fail with
   `DRAFT_DISTRICT_MISMATCH`, `CROSS_DISTRICT_CITATION`, or
   `UNKNOWN_CITATION_ID` when a draft or citation is not aligned with
   the request district.
6. **Audit.** Every runtime audit row and telemetry event carries
   `district_id` alongside `correlation_id`.

Evidence retrieval is abstracted behind
[`app/evidence/retrieval.py::EvidenceRetriever`](../../services/api/app/evidence/retrieval.py).
The concrete retriever in this build is
[`FixtureEvidenceRetriever`](../../services/api/app/evidence/fixtures.py),
which serves purely synthetic per-district fixtures. Production would
swap in a Fabric-backed retriever with the same interface.

## Rationale

- Cross-tenant leaks in agentic systems are typically failures of
  *convention*, not code. Making `district_id` a required field forces
  every developer touching an envelope or a citation to think about
  isolation.
- Contracts + JSON Schema enforcement catch drift at the wire boundary,
  before a violation can reach the UI or audit log.
- The Validator Agent's deterministic checks provide a final gate:
  even if an upstream mistake leaks a foreign citation into a draft,
  it will be rejected before the recommendation is surfaced.
- Evidence retrieval is fronted by an abstraction so that when the
  Fabric-backed retriever is added, no agent code changes.

## Consequences

- Existing callers (frontend, tests, seeded plans) now include
  `district_id`. The demo uses `DIST-DEMO`; production would use real
  district identifiers.
- Runtime audit and telemetry rows are wider by four safe fields:
  `correlation_id`, `district_id`, `evidence_count`, `citation_count`,
  `validator_status`. None of them contain prompts, completions, or
  raw user text.
- If evidence retrieval fails for a district, the coordinator returns a
  typed `evidence_missing` status and does **not** attempt to fall back
  to another district or to a "generic" catalog.

## Remaining production hardening

- Real Fabric-backed retriever (per-district workspace/lakehouse). This
  build only ships the interface + a fixture retriever.
- Row- or column-level security on the Fabric side, so a compromised
  application principal cannot read another district's rows.
- Per-district Foundry projects or per-district agent bindings, if
  future tenancy models require reasoning-side isolation as well.
- Signed audit records tied to `district_id` and a district-scoped key
  ring.
