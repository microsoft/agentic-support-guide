# Agents vs. bigger prompts

> **Customer question**: *Why not just keep adding more context to the
> prompt? Why do we need multiple agents?*

That is the right question to ask. This document answers it in terms
of **this** solution — not generic agent marketing.

## Short answer

The recommendation workflow in this repo has to enforce five things at
the same time:

1. **District-scoped data.** A recommendation for District A must
   never reference District B's evidence.
2. **Evidence-backed output.** Every recommendation must attach at
   least one citation from a district-approved source.
3. **Deterministic guardrails.** The output has to be checked against
   contracts, banned determinations (diagnosis, placement,
   legal/medical), and citation integrity — every single time.
4. **Auditable handoffs.** Each step must leave a safe, structured
   trace record (no prompt or completion text).
5. **Human review before anything is used.** Draft, pending, approved,
   rejected are first-class states.

A single "big prompt" collapses all five responsibilities into one
opaque model call. When something goes wrong you cannot tell whether
the model reasoned incorrectly, retrieved the wrong evidence, or
skipped a guardrail. When something goes right you cannot prove that
the guardrails ran.

## What "one big prompt" actually costs you here

| Concern | Bigger-prompt approach | Multi-agent approach (this repo) |
| --- | --- | --- |
| District isolation | Enforced only by prompt text ("don't mix districts"). One retrieval bug leaks another district into context. | `district_id` is required in every contract; validator has deterministic `CROSS_DISTRICT_CITATION` and `DRAFT_DISTRICT_MISMATCH` checks. |
| Evidence and citations | Ungrounded unless you also inline all documents. Citations are optional strings. | `Citation` is a typed schema; `minItems: 1`; validator raises `MISSING_CITATIONS` / `UNKNOWN_CITATION_ID`. |
| Guardrails | Instructions in prompt; model can talk itself out of them. | Deterministic Python checks in the Validator Agent; regexes for forbidden determinations. |
| Traceability | One opaque model call. | `agent-hop-start`, `agent-hop-end` trace steps per agent, with contract IDs and status codes. |
| Auditability | One row per request with no structure. | `correlation_id`, `district_id`, `evidence_count`, `citation_count`, `validator_status` per hop. No prompt/completion text stored. |
| Replaceability | Whole prompt has to be re-tuned to change any behavior. | One agent can be re-versioned, re-bound, or swapped without touching the others. |
| Testability | Golden-output tests against the whole call. | Per-agent unit tests; contract tests at each hop; validator tests independently. |
| Handling large PDFs | Everything has to fit in the context window. | Evidence retrieval is a separate step; only relevant chunks flow into the recommender. |
| Safety of model failure | A hallucinated citation or foreign district reference can reach the UI. | Validator rejects it; response is `validation_failed` with `failed_fields` and a `safe_summary` — no raw critique surfaced. |

## Why *this* solution needs it

The three agents each have a **narrow, verifiable job**:

- **Data Analyst Agent** — read the request and district context,
  produce a typed observation payload. It never writes a
  recommendation.
- **Support Recommendation Agent** — take observations + retrieved
  evidence, propose supports, attach citations. It cannot approve
  itself.
- **Validator Agent** — check the draft against contracts, citation
  integrity, and forbidden determinations. It can reject or request
  one repair pass. It never fabricates content.

(Historical notes may refer to the recommender as "Interventionist" or
"Instructional Expert". Those labels are not used in code or UI.)

The coordinator orchestrates these hops, generates a `correlation_id`,
performs evidence retrieval, and stamps `district_id` on every
payload. Every step is a **typed contract** (JSON Schema in
`/contracts/v1/`), so a break anywhere shows up as a schema validation
error, not as a subtle output regression.

## What multiplying prompt context does not fix

- **Tenancy.** No prompt tells the model, at runtime, that it is
  allowed to see District A and not District B. That is a data-plane
  problem. Retrieval scoping and validator checks solve it. Prompt
  text does not.
- **Regulatory-adjacent phrasing.** A single "don't diagnose"
  instruction is not a regulator-defensible control. A deterministic
  regex check in the Validator Agent, with an audit trail, is.
- **Change management.** Prompts drift silently. Contracts, agent
  versions, and audit rows are diff-able and reviewable.
- **Human review.** A prompt cannot enforce "pending until a human
  approves". The `human_review_state` field and the
  `/review` endpoint do.

## When one prompt is fine

For a single-tenant, single-purpose assistant with no evidence
requirement and no regulatory sensitivity, one prompt is fine and
cheaper. That is not this workload.

## See also

- [`docs/architecture.md`](architecture.md)
- [`docs/adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)
- [`docs/adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)
- [`docs/foundry-fabric-deep-dive.md`](foundry-fabric-deep-dive.md)
- [`docs/genaiops.md`](genaiops.md)
