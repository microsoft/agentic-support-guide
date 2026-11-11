# Agentic Support Guide — Workshop

Build a multi-agent system on Microsoft Foundry using the Microsoft Agent
Framework, then deploy it, ground it, guard it, evaluate it and operate it.

**Duration:** 4 hours 25 minutes hands-on, plus Module 0 as prework.
**Format:** every module is something you do.

## Scenario

You build an internal tool for a company that owns several car dealership
groups. A manager describes a problem in their own words — slow enquiry
response, stale listings, low test-drive conversion — and the tool returns a
support plan that cites the group's own documents.

All data is synthetic. Three dealer groups (`GROUP-A`, `GROUP-B`,
`GROUP-DEMO`) each own their evidence and their saved plans, and a plan for
one group must never cite another group's evidence. That rule makes the
isolation and grounding work concrete. No module asks you to bring real data.

## Choose a track

The workshop comes in two languages, and they are the same workshop: the same
modules, the same app, the same API and UI, the same agent definitions in
`agents/`, the same Azure resources and the same results. Pick the language
you want to read and write all day.

| Track | Agent Framework | App | Start here |
| --- | --- | --- | --- |
| **Python** | `agent-framework` for Python | FastAPI | [Module 0 (Python)](python/module-0-provision.md) |
| **.NET** | `Microsoft.Agents.AI` for .NET | ASP.NET Core | [Module 0 (.NET)](dotnet/module-0-provision.md) |

Each track provisions its own environment, so two people on one subscription
can take different tracks. Where the two frameworks genuinely behave
differently, the module says so; the full list, with the reason for each, is
[conformance/allowed_differences.yaml](../conformance/allowed_differences.yaml).

## Learning objectives

In this workshop, you learn how to:

- Provision a Foundry project, model deployments, search and storage with
  Terraform, and deploy an API and UI to App Service.
- Write an agent, give it a tool, and hold a multi-turn session.
- Build a `WorkflowBuilder` graph with executors, edges and a conditional
  repair loop.
- Publish versioned prompt agents, and run your own code as a hosted agent
  with its own identity.
- Ground an application in retrieved evidence and enforce per-group isolation.
- Route across models and measure what routing costs and returns.
- Measure what platform guardrails block, and what only your own code can.
- Grade agent output numerically and gate regressions.
- Trace a request, diagnose a failed deployment, and forecast cost.

## Prerequisites

- An Azure subscription where you hold **Owner**, or **Contributor** *and*
  **User Access Administrator**, at subscription scope. Terraform creates a
  resource group *and* role assignments inside it, so `Contributor` alone
  fails.
- The ability to hold **Foundry Account Owner** on your own AI Services
  account. Module 8 needs it, and `terraform apply` does not grant it. If your
  tenant blocks self-assignment, arrange it before the workshop.
- Quota in your region for **20 units of `gpt-4.1-mini` on `DataZoneStandard`**,
  **10 units of `model-router` on `GlobalStandard`**, and room for **one Azure
  AI Search service on `basic`**. A quota increase takes business days.
- Windows 10 or 11, with your own Windows user account, your own clone of this
  repo, and permission to run local PowerShell scripts. Every command you
  type is PowerShell and every path is a Windows path; the scripts those
  commands run are a mix of PowerShell and your track's language.
- Git 2.40, PowerShell 7.4, Azure CLI 2.84 plus its `application-insights`
  extension, Terraform 1.9, Node.js 22 LTS, and Visual Studio Code. Do not pin
  an older Azure CLI — `az search usage list` is missing from older builds.
- For the **Python** track, Python 3.13. For the **.NET** track, the .NET 10
  SDK, version 10.0.404 or later.
- Network access to the Azure endpoints the SDKs call, including
  `*.services.ai.azure.com`, and no TLS-inspecting proxy in front of them.
- Comfort reading and editing your track's language — Python (functions,
  classes, `async`/`await`) or C# (classes, records, lambdas,
  `async`/`await`). Modules 2 and 3 have you edit it.

Module 0 ([Python](python/module-0-provision.md), [.NET](dotnet/module-0-provision.md))
walks through the setup and ends with a passing `verify-demo.ps1`. **Complete
it before day one** — it takes 45 to 75 minutes, and `terraform apply` alone
runs 15 to 20 minutes when it works.

> Organizing this for a group? Quota headcount maths, class-size limits,
> resource counts and cost are in
> [Plan this workshop for a group](plan-this-workshop.md).

## Modules

| # | Module | What you do | Time |
| --- | --- | --- | --- |
| 0 | Provision your environment — [Python](python/module-0-provision.md) · [.NET](dotnet/module-0-provision.md) | Stand up a Foundry project, model deployments, Azure AI Search and storage with Terraform | **Prework**, 45-75 min |
| 1 | Deploy the app — [Python](python/module-1-deploy-the-app.md) · [.NET](dotnet/module-1-deploy-the-app.md) | Ship an API and UI to App Service and prove your build is the one serving | 25 min |
| 2 | Your first agent — [Python](python/module-2-first-agent.md) · [.NET](dotnet/module-2-first-agent.md) | Write an agent, give it a tool, and hold a multi-turn session | 25 min |
| 3 | Workflows — [Python](python/module-3-workflows.md) · [.NET](dotnet/module-3-workflows.md) | Build a `WorkflowBuilder` graph with executors, edges and a conditional repair loop | 35 min |
| 4 | Prompt agents — [Python](python/module-4-prompt-agents.md) · [.NET](dotnet/module-4-prompt-agents.md) | Define an agent declaratively and publish versions to Foundry | 25 min |
| 5 | Hosted agents — [Python](python/module-5-hosted-agents.md) · [.NET](dotnet/module-5-hosted-agents.md) | Run your own code as a Foundry-managed agent with its own identity | 30 min |
| 6 | Ground it with RAG — [Python](python/module-6-rag.md) · [.NET](dotnet/module-6-rag.md) | Wire retrieval into the running app and enforce per-group isolation | 35 min |
| 7 | Model router — [Python](python/module-7-model-router.md) · [.NET](dotnet/module-7-model-router.md) | Route across models and measure what it costs and returns | 20 min |
| 8 | Guardrails — [Python](python/module-8-guardrails.md) · [.NET](dotnet/module-8-guardrails.md) | Measure what the platform blocks and what only your code can | 25 min |
| 9 | Evaluation — [Python](python/module-9-evaluation.md) · [.NET](dotnet/module-9-evaluation.md) | Grade agent output numerically and gate regressions | 25 min |
| 10 | Operate — [Python](python/module-10-operate.md) · [.NET](dotnet/module-10-operate.md) | Trace a request, diagnose a failed deployment, and forecast cost | 20 min |

Modules 2 and 3 matter most if you have never written an agent. Everything
after them assumes you know what an agent, a tool, an executor and an edge
are.

## The domain rule

Nothing this system produces is a determination — not a pricing, credit,
compliance, safety or staffing decision. Every output carries a human-review
caveat and the validator rejects drafts that lack one. This shapes the agent
instructions, the validator and the evaluation criteria, and you will see it
enforced in code.

## Orchestration pattern

Sequential, with one conditional repair edge — not handoff, concurrent, group
chat or magentic. [docs/orchestration-patterns.md](../docs/orchestration-patterns.md)
covers what each of those is and why this one was chosen.

## Repository layout

| Path | Contents |
| --- | --- |
| `agents/` | Agent definitions — `agent.md` + `manifest.yaml` + `schemas/`, shared by both tracks |
| `apps/web/` | React UI, shared by both tracks |
| `evals/` | Synthetic evaluation cases, shared by both tracks |
| `conformance/` | Recorded behaviour both tracks must reproduce, and the allowed differences |
| `python/services/api/` | Python: FastAPI backend, workflow graph, evidence retrieval |
| `python/infra/` | Python: Terraform |
| `python/scripts/` | Python: publish, validate, evaluate, provision, deploy, smoke test |
| `workshop/python/code/` | Python: the runnable samples used in Modules 2 and 3 |
| `dotnet/services/api/` | .NET: ASP.NET Core backend, workflow graph, evidence retrieval |
| `dotnet/infra/` | .NET: Terraform |
| `dotnet/scripts/` | .NET: publish, validate, evaluate, provision, deploy, smoke test |
| `workshop/dotnet/code/` | .NET: the runnable samples used in Modules 2 and 3 |

Complete Module 0 for your track before the workshop, then start at Module 1
([Python](python/module-1-deploy-the-app.md), [.NET](dotnet/module-1-deploy-the-app.md)).
