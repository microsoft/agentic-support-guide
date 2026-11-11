# Getting started for new teams

This page is the learning-oriented entry point for anyone new to
agentic applications, Microsoft Foundry, DevOps, MLOps, or GenAIOps.
Read this first, in order, before opening code. Every term used here
has a plain-language entry in the [Glossary](glossary.md).

The application is implemented twice, once in Python and once in .NET, and
the two tracks behave the same; see
[Choose a track](../workshop/README.md#choose-a-track). Where this page names
a source file or a command, it names both.

## Who this repo is for

- Engineers or solution architects who want a working, opinionated
  example of a multi-agent workflow on Microsoft Foundry.
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
  Agent** reviews synthetic dealership signals and writes a short evidence
  summary. It does not propose changes.
- [`agents/support-recommender`](../agents/support-recommender) — the
  **Support Recommendation Agent** proposes a structured plan drawn
  strictly from an allowed catalog.
- [`agents/validator`](../agents/validator) — the **Validator Agent**
  checks structure, required caveats, and grounding. Deterministic
  rules in code decide pass/fail; the LLM critique is advisory.

Each agent folder contains only configuration:

- `agent.md` — instructions the ephemeral agent sees (source of truth
  for prompts).
- `manifest.yaml` — runtime metadata (agent name, response format,
  temperature, contract references).
- `schemas/` — agent-local input/output shapes.

The **runtime** for each role is an in-process Agent Framework agent in
the API backend, calling a Microsoft Foundry model deployment. The role
code — [`python/services/api/app/agents`](../python/services/api/app/agents)
in the Python track,
[`dotnet/services/api/AgenticSupportGuide.Api/Agents`](../dotnet/services/api/AgenticSupportGuide.Api/Agents)
in the .NET track — is a thin wrapper that builds the user message and
calls the ephemeral agent through `MafAgentRuntime`
([`maf_runtime.py`](../python/services/api/app/foundry_agents/maf_runtime.py) /
[`MafRuntime.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafRuntime.cs)).
There is no local language-model call in the recommendation path.

## What the coordinator is (and is not)

The **coordinator** is deterministic code in
[`python/services/api/app/workflows/coordinator.py`](../python/services/api/app/workflows/coordinator.py)
(Python) or
[`dotnet/services/api/AgenticSupportGuide.Api/Workflows/Coordinator.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Coordinator.cs)
(.NET). It:

- bounds user text,
- runs the three role agents in sequence as an Agent Framework workflow,
- stops the run when an agent's reply does not parse into its typed
  contract,
- runs at most one repair pass if the validator rejects the draft,
- produces a predictable failure taxonomy the UI can render safely.

The coordinator **is not a fourth agent**. It does not talk to a
language model, does not appear as an assistant in Foundry, and does
not appear in any prompt. It is regular code that unit tests exercise
with a fake Foundry client. Anywhere you see "the coordinator does X,"
substitute "a plain function in the API does X."

## What Microsoft Foundry provides

Microsoft Foundry is Microsoft's Azure-native platform for building and
running language-model workloads. This repo relies on three pieces of
it:

- **Model deployments.** Serverless capacity on a chosen model and
  region, billed per token, provisioned by Terraform in
  [`python/infra`](../python/infra) or [`dotnet/infra`](../dotnet/infra),
  one root per track.
- **Foundry projects.** A project resource that scopes agents, model
  deployments, RBAC, and observability. This repo provisions one
  project as part of Terraform.
- **Foundry Agent Service.** The agent surface in the portal. The three coordinator
  roles do *not* run here: each is an in-process Agent Framework agent in
  the API backend, built from instructions loaded at startup from the
  on-disk `agent.md` and `manifest.yaml` files, calling a Foundry model
  deployment through `MafAgentRuntime`. Those files are checked offline by
  [`python/scripts/validate_agent_definitions.py`](../python/scripts/validate_agent_definitions.py)
  or [`dotnet/scripts/validate_agent_definitions.cs`](../dotnet/scripts/validate_agent_definitions.cs)
  and published to the portal as versioned prompt agents by
  [`python/scripts/publish_prompt_agents.py`](../python/scripts/publish_prompt_agents.py)
  or [`dotnet/scripts/publish_prompt_agents.cs`](../dotnet/scripts/publish_prompt_agents.cs).

Authentication is keyless: the backend uses `DefaultAzureCredential`
and holds only a bearer token acquired for the Foundry endpoint. No
model API keys are stored or written to disk.

## What DevOps means for this repo

DevOps is the practice of automating build, test, deployment, and
configuration.

In this repo, that shows up as:

- **Version control** for everything: agent instructions, contracts,
  Terraform, and application code all live in the same monorepo.
- **Infrastructure as code.** [`python/infra`](../python/infra) and
  [`dotnet/infra`](../dotnet/infra) each provision the Foundry project,
  model deployment, RBAC, Log Analytics, and Application Insights with
  Terraform, one environment per track.
- **Repeatable local dev.** Backend and frontend both start from
  documented commands with no hidden environment.
- **Local quality gates.** `ruff`, `mypy` and `pytest` (Python),
  `dotnet format`, `dotnet build` and `dotnet test` (.NET),
  `npm run build`, `npm run test`, `terraform fmt`, and
  `terraform validate` can be run by any developer before pushing.
- **CI.** [`.github/workflows/ci-python.yml`](../.github/workflows/ci-python.yml)
  and [`.github/workflows/ci-dotnet.yml`](../.github/workflows/ci-dotnet.yml)
  run each track's gates plus its `validate_agent_definitions` script, and
  [`.github/workflows/ci-shared.yml`](../.github/workflows/ci-shared.yml)
  runs the frontend's, on every pull request. No Azure credentials are
  needed for any of them.

Remaining gap: CI proves the code is well-formed, not that agent output
is good. Nothing blocks a merge on a live-model eval score.

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

Those choices live in your track's Terraform root
([`python/infra`](../python/infra) or [`dotnet/infra`](../dotnet/infra))
and in each agent's
[`manifest.yaml`](../agents/data-analyst/manifest.yaml), which is also where
the role-to-model-deployment binding is recorded.

Remaining gap: this repo has no automated model-version canary or
rollback. Deployment changes are manual via Terraform and the deploy script.

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
4. Open your track's contracts —
   [`python/services/api/app/agents/shared/contracts.py`](../python/services/api/app/agents/shared/contracts.py)
   or
   [`dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs)
   — and skim one agent's output contract. (2 min)
5. Open [`python/services/api/app/workflows/coordinator.py`](../python/services/api/app/workflows/coordinator.py)
   and read `AgentCoordinator.run()`, or
   [`dotnet/services/api/AgenticSupportGuide.Api/Workflows/Coordinator.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/Coordinator.cs)
   and read `AgentCoordinator.RunAsync()`. (5 min)
6. Skim [Security and privacy](security-and-privacy.md) and
   [Observability](observability.md). (1 min each)

After that you know the shape of the codebase and can navigate the
rest by search.

## What to run for a customer demo

Only commands that already exist in this repo. Full setup steps live
in the root [README](../README.md) under **Set up Microsoft Foundry**,
for both tracks. In summary:

1. `az login` and set the subscription.
2. `terraform apply` in your track's Terraform root,
   [`python/infra`](../python/infra) or [`dotnet/infra`](../dotnet/infra).
3. `./python/scripts/populate-env.ps1` to write `python/services/api/.env`,
   or `./dotnet/scripts/populate-env.ps1` to write
   `dotnet/services/api/.env`, from Terraform outputs.
4. `python python/scripts/validate_agent_definitions.py` or
   `dotnet run dotnet/scripts/validate_agent_definitions.cs` to check the
   agent definitions. There is nothing to deploy - agents are ephemeral.
5. Start the backend. Python: `uvicorn app.main:app --host 127.0.0.1
   --port 8000 --reload --env-file .env`; the `--env-file` flag is
   required, because the app does not load `.env` by itself. .NET:
   `./dotnet/scripts/run-backend.ps1`, which loads `.env` into the backend
   process for the same reason.
6. Start the frontend: `npm run dev` in [`/apps/web`](../apps/web).
7. Confirm `GET /api/health/details` reports
   `"customer_demo_ready": true`.

For the demo talk track, see the [customer demo guide](../demo/README.md).

## Where to go next

- [Architecture](architecture.md) — the target pattern and this repo's
  implementation.
- [Architecture diagram](architecture-diagram.md) — the container view.
- [GenAIOps](genaiops.md) — concept-first, then repo practices.
- [Security and privacy](security-and-privacy.md).
- [Observability](observability.md).
- [Glossary](glossary.md) — plain-language definitions.
- [ADR 0006 — published prompt agents](adr/0006-published-prompt-agents.md)
  — the current decision. It supersedes ADR 0005, which superseded
  [ADR 0002](adr/0002-agent-hosting-remote-foundry.md).
