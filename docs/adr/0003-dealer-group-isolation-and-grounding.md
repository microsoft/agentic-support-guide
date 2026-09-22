# ADR 0003 - Dealer group isolation and grounding

Supersedes: none
Status: Accepted
Date: 2026-08-19

## Context

Customer data lives in Microsoft Fabric with a **separate workspace and
lakehouse per dealer group**. Each dealer group's data must stay within that
dealer group: recommendations produced for Dealer group A can never surface
data, citations, or documents from Dealer group B. This is a hard product
requirement.

The three-agent workflow already existed. What was missing was a
first-class notion of `dealer_group_id` across the request, agent
handoffs, evidence retrieval, audit records, and trace metadata.

## Decision

Introduce `dealer_group_id` as a **required, contract-level field** at every
layer of the recommendation workflow:

1. **HTTP boundary.** `SupportPlanRequest` requires `dealer_group_id`
   matching pattern `^[A-Z0-9][A-Z0-9\-]{1,31}$`.
2. **JSON Schemas.** `dealer_group_id` is required in every payload in
   `/contracts/v1/*.schema.json` (request, result, and citation
   payloads).
3. **Pydantic contracts.** `DataAnalystOutput`, `SupportRecommendationDraft`,
   `ValidatorReport`, and `Citation` all require `dealer_group_id`.
4. **Coordinator.** `CoordinatorRequest.dealer_group_id` is passed into
   every agent context and stamped on every envelope payload.
5. **Validator.** Deterministic checks fail with
   `DRAFT_DEALER_GROUP_MISMATCH`, `CROSS_DEALER_GROUP_CITATION`, or
   `UNKNOWN_CITATION_ID` when a draft or citation is not aligned with
   the request dealer group.
6. **Audit.** Every runtime audit row carries
   `dealer_group_id` alongside `correlation_id`.

Evidence retrieval is abstracted behind
[`app/evidence/retrieval.py::EvidenceRetriever`](../../services/api/app/evidence/retrieval.py).
The concrete retriever in this build is
[`FixtureEvidenceRetriever`](../../services/api/app/evidence/fixtures.py),
which serves purely synthetic per-dealer group fixtures. Production would
swap in a Fabric-backed retriever with the same interface.

## Rationale

- Cross-tenant leaks in agentic systems are typically failures of
  *convention*, not code. Making `dealer_group_id` a required field forces
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
  `dealer_group_id`. The demo uses `GROUP-DEMO`; production would use real
  dealer group identifiers.
- Runtime audit rows are wider by five safe fields:
  `correlation_id`, `dealer_group_id`, `evidence_count`, `citation_count`,
  `validator_status`. None of them contain prompts, completions, or
  raw user text.
- If evidence retrieval fails for a dealer group, the coordinator returns a
  typed `evidence_missing` status and does **not** attempt to fall back
  to another dealer group or to a "generic" catalog.

## Remaining production hardening

- Real Fabric-backed retriever (per-dealer group workspace/lakehouse). This
  build only ships the interface + a fixture retriever.

> **Since closed.** `FoundryIQEvidenceRetriever` now implements that
> interface against Azure AI Search, selected by `EVIDENCE_SOURCE`. Module 6
> of the workshop builds it.
- Row- or column-level security on the Fabric side, so a compromised
  application principal cannot read another dealer group's rows.
- Per-dealer group Foundry projects or per-dealer group agent bindings, if
  future tenancy models require reasoning-side isolation as well.
- Signed audit records tied to `dealer_group_id` and a dealer group-scoped key
  ring.
