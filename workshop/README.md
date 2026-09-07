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

The order follows a real delivery lifecycle: stand up infrastructure, ship
the app, then build the AI on top of something that already runs.

| # | Module | Phase | Time | What you build |
| --- | --- | --- | --- | --- |
| 0 | [Provision infrastructure](module-0-provision.md) | DevOps | 20 min | Foundry project, models, Search, storage, App Service |
| 1 | [Deploy the app to Azure](module-1-deploy-app.md) | DevOps | 45 min | API and UI live on App Service, with a build check |
| 2 | [Your first prompt agent](module-2-prompt-agent.md) | GenAIOps | 45 min | A versioned agent in the portal, no code |
| 3 | [Ground it with Foundry IQ](module-3-foundry-iq.md) | GenAIOps | 60 min | Knowledge base wired into the running app |
| 4 | [Orchestrate three agents](module-4-orchestration.md) | GenAIOps | 60 min | Deterministic multi-agent coordination |
| 5 | [Model router](module-5-model-router.md) | Optimize | 45 min | Measured routing across models |
| 6 | [Guardrails](module-6-guardrails.md) | Secure | 45 min | Measured map of what the platform stops |
| 7 | [Hosted agents](module-7-hosted-agent.md) | Deploy | 60 min | Deploy, break, fix and roll back your own agent |
| 8 | [Evaluation](module-8-evaluation.md) | Measure | 60 min | Numeric grades and a regression gate |
| 9 | [Operate](module-9-operate.md) | Operate | 75 min | Traces, a real outage, recovery, cost |

Roughly two days with discussion, or one long day if you move quickly.

Module 9 is the long one and most of it is waiting: the deliberate failure
takes ten minutes to be declared dead, and the recovery deploy takes about
as long again. That wait is the lesson, so do not skip it — but do start
something else while it runs.

Modules 0, 1 and 9 are the DevOps spine. Modules 2 through 8 are GenAIOps.
They are interleaved on purpose: the AI work lands in an app that is already
deployed, monitored and rollback-able, which is the only way any of it
reaches production.

## The through-line

Each module exists because the previous one hit a wall:

0. **M0** — Terraform gives you a Foundry project and somewhere to run.
   But an empty App Service serves nobody.
1. **M1** — deploying the app fixes that. But it answers from canned data.
2. **M2** — a prompt agent answers questions. But it confidently answers
   things it has no knowledge of.
3. **M3** — grounding it in district knowledge fixes that, and you point the
   *running* app at it. But one agent cannot enforce a multi-step process.
4. **M4** — three coordinated agents can. But now you are paying a frontier
   model for work a small model could do.
5. **M5** — a router fixes the cost. But nothing stops harmful input or
   output.
6. **M6** — guardrails do. But your agent still cannot use custom
   dependencies or hold its own identity.
7. **M7** — a hosted agent can. But you still have no idea whether any of it
   is actually *good*.
8. **M8** — evaluation tells you. But none of it survives contact with a
   Tuesday afternoon incident.
9. **M9** — operating it does.

Do not skip ahead. Each wall is the point.

## Prerequisites

- An Azure subscription you can create resources in
- `az` CLI, Terraform ≥ 1.9, Python 3.13, Node 22+
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
| `scripts/` | Publish, validate, evaluate, provision, deploy, smoke test |
| `.github/workflows/` | CI on every push, deploy on demand |

## Facilitator notes

- **Search throughput.** One replica serves roughly three concurrent semantic
  requests plus a short queue. Thirty learners querying at once will throttle.
  Raise `search_replica_count` or run Module 3 in waves.
- **Isolation.** `Search Service Contributor` covers the whole search
  service; Azure AI Search has no per-index RBAC. Index prefixes are a naming
  convention, not a security boundary. Acceptable in a throwaway subscription
  only — see the note at the end of Module 0.
- **Suffixes.** `WORKSHOP_LEARNER_SUFFIX` is mandatory for publishing. It is
  what stops learners overwriting each other's agents.
- **Cost.** Tear down with `terraform -chdir=infra destroy` when finished. The
  Search service is the largest line item.
