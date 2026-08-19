# Foundry + Fabric deep dive

This is the "explain it clearly" companion to
[`docs/architecture.md`](architecture.md) and the ADRs in
[`docs/adr/`](adr/). It is written for a reader who is new to
Azure AI Foundry and Microsoft Fabric.

## What Azure AI Foundry does in this repo

**Azure AI Foundry Agent Service** hosts three remote agents:

1. Data Analyst Agent
2. Support Recommendation Agent (historical names: "Interventionist",
   "Instructional Expert" — not used in code)
3. Validator Agent

The FastAPI backend does not run the model. It calls Foundry over the
`azure-ai-agents` SDK and receives structured JSON back. Foundry
handles:

- Model deployment (the assigned model behind each agent)
- Agent identity + version binding
- Tracing at the model-call level
- Content-safety plumbing at the model boundary

The backend keeps responsibility for:

- Orchestration (the three-hop workflow)
- Contract enforcement (Pydantic + JSON Schema)
- District isolation
- Evidence retrieval and citation attachment
- Deterministic guardrails in the Validator Agent
- Human review lifecycle
- Runtime audit and telemetry

That split matters. Foundry is the **reasoning tier**. The backend is
the **policy and evidence tier**. Neither can compromise the other.

## What Fabric is expected to do

Microsoft Fabric is the **data tier**. In the target model:

- **One Fabric workspace per district.** No shared workspace across
  districts.
- **One lakehouse per workspace** with the district's own tables
  (attendance, assessments, roster attributes, program eligibility,
  etc.) and its own OneLake files (policies, handbooks, PDFs).
- **Row/column security** and role assignments at the workspace level
  so that even a compromised backend principal cannot read another
  district's rows.
- **No cross-workspace joins**. Grounding never spans districts.

Nothing in this repo talks to Fabric today. The `EvidenceRetriever`
interface is where that integration lands.

## Where the retriever plugs in

```
services/api/app/evidence/
  retrieval.py    <- EvidenceRetriever Protocol (stable interface)
  fixtures.py     <- FixtureEvidenceRetriever (current implementation)
```

A production build swaps `FixtureEvidenceRetriever` for a
`FabricEvidenceRetriever` that:

1. Takes `district_id` and `category`.
2. Resolves the district's Fabric workspace + lakehouse from a bound
   configuration (never inferred at runtime from user input).
3. Executes a scoped SQL / OneLake query for structured items and a
   scoped search for unstructured items.
4. Returns a typed `EvidenceBundle` with per-item `district_id`
   stamped by the retriever, not by the caller.

The coordinator, recommender wrapper, and validator do not change.

## Where Foundry IQ / Fabric IQ could fit

Both give you grounding over unstructured content with citation
metadata. In this repo they would appear as an implementation of
`EvidenceRetriever`. The wire-facing `Citation` type already supports
`source_type = document | policy | resource` with
`section_or_page` and `evidence_summary`, so a retrieval hit with a
page range and highlighted passage maps directly.

Neither is wired up in this repo. See
[ADR 0004](adr/0004-grounding-and-citations.md).

## What is synthetic in this prototype

- All evidence returned by `FixtureEvidenceRetriever` is
  `source_type = synthetic_fixture`.
- The district IDs `DIST-A`, `DIST-B`, `DIST-DEMO` are placeholders.
- Seeded plans use `DIST-DEMO` and a stub citation so the UI has
  something to render before a real recommendation is made.
- No real district, school, staff, student, or document names appear
  anywhere.

## What must be decided before production

- Whether districts get **per-district Foundry projects** or share a
  single Foundry project with per-district agent bindings.
- Where district → Fabric-workspace mapping lives (Terraform-owned,
  vault-owned, or configuration store).
- How managed identities are scoped so the backend can only reach the
  workspace matching the incoming `district_id`.
- Whether human review approvals need external signing (e.g., a
  district approver's signed record) or in-app audit is sufficient.
- How PDF ingestion is governed: who uploads, who approves the
  document as citable, and how the retriever knows it is approved.

## See also

- [`docs/architecture.md`](architecture.md)
- [`docs/adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)
- [`docs/adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
- [`docs/security-and-privacy.md`](security-and-privacy.md)
- [`docs/agents-vs-prompts.md`](agents-vs-prompts.md)
