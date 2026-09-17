# ADR 0004 - Grounding and citations

Supersedes: none
Status: Accepted
Date: 2026-08-19

## Context

Customers asked for **evidence-backed recommendations with source
attribution**. In practice this means:

1. Every recommendation must be able to point back to one or more
   evidence items (a dealer group benchmark, a policy excerpt, an approved
   resource, a dealer group-uploaded PDF, etc.).
2. Sources must be **dealer group-scoped** (see
   [ADR 0003](0003-dealer-group-isolation-and-grounding.md)).
3. Unstructured content (PDFs, handbooks) matters as much as
   structured data.

## Decision

Introduce a first-class `Citation` type and an `EvidenceRetriever`
abstraction.

### Contract-level

- New Pydantic type `Citation` and JSON Schema
  [`contracts/v1/citation.schema.json`](../../contracts/v1/citation.schema.json).
- Each citation carries: `citation_id`, `dealer_group_id`, `source_type`
  (structured_data | document | policy | resource | synthetic_fixture),
  `source_title`, `section_or_page`, `evidence_summary`, `source_ref`,
  `retrieved_at`, `confidence`.
- `support-recommendation-result.schema.json` requires
  `citations: minItems 1`. A recommendation with no evidence cannot
  pass protocol validation.
- Validator Agent adds `MISSING_CITATIONS`, `CROSS_DEALER_GROUP_CITATION`,
  and `UNKNOWN_CITATION_ID` issue codes.

### Runtime abstraction

- [`app/evidence/retrieval.py::EvidenceRetriever`](../../services/api/app/evidence/retrieval.py)
  is the stable interface used by the coordinator.
- [`app/evidence/fixtures.py::FixtureEvidenceRetriever`](../../services/api/app/evidence/fixtures.py)
  is the current implementation. Serves purely synthetic, per-dealer group
  fixtures.
- The coordinator calls the retriever **once per request, up front**,
  and passes the resulting `EvidenceBundle` to the recommender wrapper.
- The recommender wrapper resolves the remote agent's `cited_ids` list
  against the bundle and attaches the resolved `Citation` objects to
  the draft.

### Flow

```
POST /api/recommendations/support-plan (dealer_group_id required)
    -> Coordinator generates correlation_id
    -> EvidenceRetriever.retrieve(dealer_group_id, category)
    -> Data Analyst Agent  (dealer_group_id stamped on output)
    -> Support Recommendation Agent (bundle + cited_ids)
        -> Wrapper attaches citations from bundle
    -> Validator Agent
        -> checks: missing citations, cross-dealer group refs, unknown ref
    -> Optional one-shot repair
    -> Recommendation surfaces citations to the UI
```

## Where Foundry IQ / Fabric IQ could fit

Both product surfaces provide grounding over structured and
unstructured content. In this repo, either could be plugged in as a
new `EvidenceRetriever` implementation:

- Structured lookups become `structured_data` citations.
- Dealer group-approved PDFs become `document` citations with a
  `section_or_page` from the retrieval hit.
- Dealer group policy documents become `policy` citations.
- Dealer group resource libraries become `resource` citations.

None of that is implemented in this repo. It is documented here as the
intended integration surface.

## Rationale

- Making citations a first-class schema field forces every UI and
  audit consumer to accept and preserve them.
- A retrieval abstraction keeps the recommender and validator ignorant
  of the concrete backend, so tests (using the fixture retriever) and
  production (using a Fabric-backed retriever) exercise the same wire
  contract.
- Failing closed on empty evidence (via protocol validation + validator
  citation checks) means an unbacked recommendation cannot slip
  through.

## Consequences

- Every runtime path now attaches at least one citation to a passing
  recommendation. Fixture-driven demos are unchanged in shape.
- Frontend must render citations. This iteration keeps the UI minimal
  and does not redesign the recommendation card.
- Audit rows and telemetry now include `evidence_count` and
  `citation_count`.

## Remaining gaps

- No Fabric- or Foundry-IQ-backed retriever is implemented.
- No PDF ingestion pipeline is included.
- No signed-source-of-truth checkpoint on citations (they are
  synthetic).
- No relevance ranking; the fixture retriever returns everything for
  the category up to a bounded count.
