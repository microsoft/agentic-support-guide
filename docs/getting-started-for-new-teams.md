# Getting started for new teams

This page is the learning-oriented entry point for anyone new to
agentic applications, Azure AI Foundry, DevOps, MLOps, or GenAIOps.
Read this first, in order, before opening code. Every term used here
has a plain-language entry in the [Glossary](glossary.md).

## Who this repo is for

- Engineers or solution architects who want a working, opinionated
  example of a multi-agent workflow on Azure AI Foundry.
- Teams starting to experiment with agentic patterns and want to see
  how to organize agent instructions, contracts, orchestration, and
  observability without writing everything from scratch.
- Customer-facing demo owners who need a synthetic-data-only reference
  they can present without privacy risk.

This is not a production system, not a research benchmark, and not a
substitute for human review of any recommendation.

## What an agentic application is

An agentic application uses one or more language-model **agents** to
break a task into pieces, exchange typed messages between those pieces,
and produce a structured output.

Each agent has:

- a narrow role, described in natural language,
- an input contract and an output contract,
- guardrails such as allowed catalogs, required caveats, and safety
  boundaries,
- no direct access to production data.

The application is agentic (not just "an app that calls an LLM")
because more than one specialized reasoning step cooperates to solve
one request, and the pieces are wired together with an explicit
protocol.

## What an agent is in this repo

The three agents live under [`/agents`](../agents):

- [`agents/data-analyst`](../agents/data-analyst) — the **Data Analyst
  Agent** reviews synthetic learner signals and writes a short evidence
  summary. It does not propose interventions.
- [`agents/support-recommender`](../agents/support-recommender) — the
  **Support Recommendation Agent** proposes a structured plan drawn
  strictly from an allowed catalog.
- [`agents/validator`](../agents/validator) — the **Validator Agent**
  checks structure, required caveats, and grounding. Deterministic
  Python rules decide pass/fail; the LLM critique is advisory.

Each agent folder contains only configuration:

- `agent.md` — instructions the ephemeral agent sees (source of truth
  for prompts).
- `manifest.yaml` — runtime metadata (agent name, response format,
  temperature, contract references).
- `schemas/` — agent-local input/output shapes.

The **runtime** for each role is a ephemeral agent hosted on Azure AI
Foundry Agent Service. The Python code in
[`services/api/app/agents`](../services/api/app/agents) is a thin
wrapper that builds the user message and calls the ephemeral agent
through [`MafAgentRuntime`](../services/api/app/foundry_agents/maf_runtime.py).
There is no local language-model call in the recommendation path.

## What the coordinator is (and is not)

The **coordinator** is deterministic Python in
[`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py).
It:

- sanitizes user text,
- calls the three role agents in sequence,
- validates each inter-agent message against a JSON Schema in
  [`/contracts/v1`](../contracts/v1),
- runs at most one repair pass if the validator rejects the draft,
- enforces per-run and total budgets,
- produces a predictable failure taxonomy the UI can render safely.

The coordinator **is not a fourth agent**. It does not talk to a
language model, does not appear as an assistant in Foundry, and does
not appear in any prompt. It is regular code that unit tests exercise
with a fake Foundry client. Anywhere you see "the coordinator does X,"
substitute "a Python function does X."

## What Azure AI Foundry provides

Azure AI Foundry is Microsoft's Azure-native platform for building and
running language-model workloads. This repo relies on three pieces of
it:

- **Model deployments.** Serverless capacity on a chosen model and
  region, billed per token, provisioned by Terraform in
  [`/infra`](../infra).
- **Foundry projects.** A project resource that scopes agents, model
  deployments, RBAC, and observability. This repo provisions one
  project as part of Terraform.
- **Agent Service.** The hosted-agent surface. Each of the three
  agents in this repo runs as a ephemeral agent here. The sync script
  ([`scripts/validate_agent_definitions.py`](../scripts/validate_agent_definitions.py))
  creates or updates those assistants from the on-disk `agent.md` and
  `manifest.yaml` files.

Authentication is keyless: the backend uses `DefaultAzureCredential`
and holds only a bearer token acquired for the Foundry endpoint. No
model API keys are stored or written to disk.

## What DevOps means for this repo

DevOps is the practice of automating build, test, deployment, and
configuration.

In this repo, that shows up as:

- **Version control** for everything: agent instructions, contracts,
  Terraform, and application code all live in the same monorepo.
- **Infrastructure as code.** [`/infra`](../infra) provisions the
  Foundry project, model deployment, RBAC, Log Analytics, and
  Application Insights with Terraform.
- **Repeatable local dev.** Backend and frontend both start from
  documented commands with no hidden environment.
- **Local quality gates.** `ruff`, `mypy`, `pytest`, `npm run build`,
  `npm run test`, `terraform fmt`, and `terraform validate` can be run
  by any developer before pushing.
- **CI.** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs
  all of those gates plus `validate_agent_definitions.py` on every
  pull request. No Azure credentials are needed for any of them.

Remaining gap: CI proves the code is well-formed, not that agent output
is good. Scoring agent versions against `/evals` is still manual.

## What MLOps means for this repo

MLOps traditionally means managing the lifecycle of a trained model:
training runs, datasets, model artifacts, model registries,
deployment, monitoring, retraining.

This repo does not train models. It uses a pre-trained Azure OpenAI
model that Foundry hosts. The MLOps concerns that still apply are:

- Which model **deployment** is bound to each role.
- What model **version** the deployment currently serves and when it
  will auto-upgrade.
- How model retirement affects the app.

Those choices live in [`/infra`](../infra) and in each agent's
[`manifest.yaml`](../agents/data-analyst/manifest.yaml). Bindings from
role to model deployment are recorded in

Remaining gap: this repo has no automated model-version canary or
rollback. Deployment changes are manual via Terraform + sync script.

## What GenAIOps means for this repo

GenAIOps is the newer discipline that applies DevOps/MLOps rigor to
generative-AI workloads. It adds concerns that traditional ML does not
usually have:

- Version prompts and agent specs, not just model weights.
- Version the inter-agent **protocol** so schema changes are
  observable.
- Evaluate **structure and safety**, not exact prose.
- Capture **metadata-only** traces so telemetry never leaks prompts or
  completions.

See [GenAIOps](genaiops.md) for the concept-first tour and the
concrete list of practices this repo already implements versus gaps.

## How to read the repo in 20 minutes

1. Read this page. (5 min)
2. Skim [Architecture](architecture.md) — top section, "The pattern
   this repo follows." (2 min)
3. Open [`agents/data-analyst/agent.md`](../agents/data-analyst/agent.md)
   and skim the instructions. Repeat for the other two roles. (5 min)
4. Open [`contracts/v1`](../contracts/v1) and skim one request and one
   result schema. (2 min)
5. Open [`services/api/app/workflows/coordinator.py`](../services/api/app/workflows/coordinator.py)
   and read `AgentCoordinator.run()`. (5 min)
6. Skim [Security and privacy](security-and-privacy.md) and
   [Observability](observability.md). (1 min each)

After that you know the shape of the codebase and can navigate the
rest by search.

## What to run for a customer demo

Only commands that already exist in this repo. Full setup steps live
in the root [README](../README.md) under **Customer demo setup (Azure
AI Foundry)**. In summary:

1. `az login` and set the subscription.
2. `terraform apply` in [`/infra`](../infra).
3. `./scripts/populate-env.ps1` to write `services/api/.env` from
   Terraform outputs.
4. `python scripts/validate_agent_definitions.py` to check the agent
   definitions. There is nothing to deploy - agents are ephemeral.
5. Start the backend: `uvicorn app.main:app --host 127.0.0.1
   --port 8000 --reload --env-file .env`. The `--env-file` flag is
   required; the app does not load `.env` by itself.
6. Start the frontend: `npm run dev` in [`/apps/web`](../apps/web).
7. Confirm `GET /api/health/details` reports
   `"customer_demo_ready": true`.

For the demo talk track, see the "What to show in the customer demo"
section of the root README.

## Where to go next

- [Architecture](architecture.md) — the target pattern and this repo's
  implementation.
- [Architecture diagram](architecture-diagram.md) — the container view.
- [GenAIOps](genaiops.md) — concept-first, then repo practices.
- [Security and privacy](security-and-privacy.md).
- [Observability](observability.md).
- [Glossary](glossary.md) — plain-language definitions.
- [ADR 0002 — remote Foundry agent hosting](adr/0002-agent-hosting-remote-foundry.md)
  — the current decision and the gaps it leaves.
