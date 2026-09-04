# Agentic Support Guide — Workshop

A hands-on path from "one agent, no code" to "measured, guarded, evaluated
multi-agent system on Azure AI Foundry."

Every module is something you *do*. Each one ends with a checklist and a set
of questions you should be able to answer.

## The domain

A synthetic K-12 learner-support scenario. Districts hold evidence about
learners; agents help staff think about support strategies.

**Nothing this system produces is a determination.** Not educational, not
clinical, not legal, not disability-related, not placement. Every output
carries a human-review caveat, and the validator refuses drafts that lack
one. The data is entirely synthetic. This constraint is not decoration — it
shapes the agent instructions, the validator, and the evaluation criteria,
and you will see it enforced in code.

## Modules

| # | Module | Time | What you build |
| --- | --- | --- | --- |
| 0 | [Provision](module-0-provision.md) | 20 min | Foundry project, models, Search, storage |
| 1 | [Your first prompt agent](module-1-prompt-agent.md) | 45 min | A versioned agent in the portal, no code |
| 2A | [Ground it with Foundry IQ](module-2a-foundry-iq.md) | 60 min | Knowledge base + knowledge source |
| 2B | [From one agent to three](module-2b-orchestration.md) | 60 min | Deterministic multi-agent coordination |
| 3 | [Model router](module-3-model-router.md) | 45 min | Measured routing across models |
| 4 | [Guardrails](module-4-guardrails.md) | 45 min | Measured map of what the platform stops |
| 5 | [Hosted agents](module-5-hosted-agent.md) | 60 min | Deploy, break, fix and roll back your own agent |
| 6 | [Evaluation](module-6-evaluation.md) | 60 min | Numeric grades and a regression gate |

Roughly two days with discussion, or one long day if you move quickly.

## The through-line

Each module exists because the previous one hit a wall:

1. **M1** — a prompt agent answers questions. But it confidently answers
   things it has no knowledge of.
2. **M2A** — grounding it in real district knowledge fixes that. But one
   agent still cannot enforce a multi-step process.
3. **M2B** — three coordinated agents can. But now you are paying a frontier
   model for work a small model could do.
4. **M3** — a router fixes the cost. But nothing stops harmful input or
   output.
5. **M4** — guardrails do. But your agent still cannot use custom
   dependencies or hold its own identity.
6. **M5** — a hosted agent can. But you still have no idea whether any of it
   is actually *good*.
7. **M6** — evaluation tells you.

Do not skip ahead. Each wall is the point.

## Prerequisites

- An Azure subscription you can create resources in
- `az` CLI, Terraform ≥ 1.9, Python 3.13, Node 20+
- `az login` completed

## Repo orientation

| Path | What lives there |
| --- | --- |
| `agents/` | Agent definitions — `agent.md` + `manifest.yaml` |
| `contracts/v1/` | JSON Schemas for every inter-agent message |
| `services/api/` | FastAPI backend, coordinator, evidence retrieval |
| `apps/web/` | React UI |
| `infra/` | Terraform |
| `evals/` | Synthetic cases and expected checks |
| `scripts/` | Publish, validate, evaluate, provision |

## Facilitator notes

- **Search throughput.** One replica serves roughly three concurrent semantic
  requests plus a short queue. Thirty learners querying at once will throttle.
  Raise `search_replica_count` or run Module 2A in waves.
- **Isolation.** `Search Service Contributor` covers the whole search
  service; Azure AI Search has no per-index RBAC. Index prefixes are a naming
  convention, not a security boundary. Acceptable in a throwaway subscription
  only — see the note at the end of Module 0.
- **Suffixes.** `WORKSHOP_LEARNER_SUFFIX` is mandatory for publishing. It is
  what stops learners overwriting each other's agents.
- **Cost.** Tear down with `terraform -chdir=infra destroy` when finished. The
  Search service is the largest line item.
