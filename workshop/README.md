# Agentic Support Guide — Workshop

A hands-on path from "one agent, no code" to "measured, guarded, evaluated
multi-agent system on Azure AI Foundry."

Every module is something you *do*. Each one ends with a checklist and a set
of questions you should be able to answer.

**You build your own environment.** There is nothing shared here — no
facilitator-owned subscription to join, no pre-created project waiting for
you. You run `terraform apply` against a subscription you control, and every
resource is created, owned and destroyed by you. Modules 1, 7 and 9 have you
deploy broken code on purpose and watch a site go down; that only works when
the environment is yours alone.

Start with **[Prerequisites](prerequisites.md)** — permissions, quota and
tooling. Several items there depend on your tenant admin, so check them
before you begin rather than partway through Module 0.

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

The short version:

- An Azure subscription where you can create resources **and role
  assignments** (`Owner`, or `Contributor` + `User Access Administrator`)
- Permission to register an Entra application, or a fallback plan
- Model quota in your chosen region
- `az` CLI, Terraform ≥ 1.9, Python 3.13, Node 22 LTS, PowerShell 7
- `az login` completed

The full list, with the checks that catch each one early, is in
[Prerequisites](prerequisites.md).

## Repo orientation

| Path | What lives there |
| --- | --- |
| `agents/` | Agent definitions — `agent.md` + `manifest.yaml` |
| `contracts/v1/` | JSON Schemas for every inter-agent message |
| `services/api/` | FastAPI backend, coordinator, evidence retrieval |
| `apps/web/` | React UI |
| `infra/` | Terraform |
| `evals/` | Synthetic cases and expected checks |
| `scripts/` | Publish, validate, evaluate, provision, deploy, smoke test, load test |
| `.github/workflows/` | CI on every push, deploy on demand |

## Running your environment

You are the only user of everything you create here, which removes a lot of
coordination problems and leaves a few real ones.

- **Model capacity is the setting you will feel first.** The default
  `model_capacity = 10` is enough for one person clicking through one request
  at a time, and not enough the moment anything runs in parallel — every
  recommendation is four model calls, and Module 8's evaluation and Module
  5's load test both fan out. Measured against the deployed app:

  | Capacity | 15 concurrent | 30 concurrent |
  | --- | --- | --- |
  | 10 | 2/15 succeeded | 1/30 succeeded |
  | 300 | 15/15, 42s | 30/30, 33s |

  Everything else fails with `AGENT_PROVIDER_THROTTLING`. Check headroom
  with `az cognitiveservices usage list -l <region> -o table`, and reproduce
  the measurement with `python scripts/load_test.py --waves 30`.
- **Cold starts are slow.** The first burst after an idle period can time
  out — 170s wall clock cold versus 42s warm for the same 15 requests. If you
  come back to the environment after a break, send one request and wait
  before you start timing anything.
- **Search throughput.** One replica serves roughly three concurrent semantic
  requests plus a short queue, which is ample for one person. Raise
  `search_replica_count` only if you are load testing retrieval.
- **Access.** Every role goes to whoever runs `terraform apply`, so
  `additional_principal_ids` can stay empty — empty means you. Only fill it
  in if you deliberately want to let a colleague into your subscription.
- **Suffixes.** `WORKSHOP_LEARNER_SUFFIX` is mandatory for publishing. In
  your own project it is what keeps a Module 6 variant addressable alongside
  its twin, and what makes `--delete` remove exactly what you published.
- **Isolation.** `Search Service Contributor` covers the whole search
  service; Azure AI Search has no per-index RBAC. That costs you nothing here
  — the service is yours — but index prefixes are a naming convention, not a
  security boundary, and this is the pattern people carry into shared
  environments. See the note at the end of Module 0.
- **Anyone with the UI URL can use your deployment.** There is no sign-in.
  The shared key stops the API being called directly, but the web tier
  attaches that key for whoever asks, so the front door is open. The records
  are synthetic; what a stranger can actually spend is your model quota. Set
  `web_allowed_ip_ranges` if the deployment will be up for more than a
  session, and keep `model_capacity` sized to what you need.
- **The web tier rate-limits the front door.** 10 recommendations per minute
  per address, 4 at once, 30 requests per minute overall. A demo that clicks
  repeatedly, or a room sharing one outbound address, can hit it and see
  `429`. Raise it with app settings on the web app:

  ```powershell
  az webapp config appsettings set -g <rg> -n <web-app> --settings `
      RECOMMENDATION_LIMIT_PER_MIN=30 MAX_CONCURRENT_RECOMMENDATIONS=8
  ```

  The limit is per instance and held in memory, so it resets on restart.
  `scripts/load_test.py` is unaffected: it calls the API directly with the
  key, which is the point of Module 5.
- **Cost.** Tear down with `terraform -chdir=infra destroy` whenever you stop
  for more than a day. The Search service and the two App Service plans bill
  by the hour whether or not you use them.
