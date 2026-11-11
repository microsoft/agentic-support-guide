# Glossary

Plain-language definitions for the terms used across this repo's docs.
For deeper explanations of how each concept is used here, follow the
links back into the concept-first docs. Where a term points at code, both
tracks are named: the Python track under `python/` and the .NET track under
`dotnet/`.

## Agent

A specialized language-model role with a narrow job, described in
natural language, that produces structured output. In this repo, an
agent is a folder under [`/agents`](../agents) containing an
`agent.md` (instructions) and a `manifest.yaml` (runtime metadata).
An agent has no source code of its own; the runtime assembles it from those
two files at startup and caches the result until the process restarts.

## Prompt agent

An agent whose entire definition is instructions plus a model binding, with
no code. This repo's three roles are prompt agents: the runtime composes
instructions from `agent.md` in-process and makes a single-turn Responses
call. The same definitions are also published to Foundry as versioned,
visible artifacts by `python/scripts/publish_prompt_agents.py` or
`dotnet/scripts/publish_prompt_agents.cs`, but the application does not call
the published copies.

## Coordinator

Deterministic application code that builds the Agent Framework graph, runs
it, and reads the trace off the workflow's event stream. Lives in
[`python/services/api/app/workflows/`](../python/services/api/app/workflows/)
and
[`dotnet/services/api/AgenticSupportGuide.Api/Workflows/`](../dotnet/services/api/AgenticSupportGuide.Api/Workflows/).
The coordinator is **not an agent** — it does not talk to a language
model.

## Agent Service

The **Foundry Agent Service** capability. It hosts agents, their
versions, and — for hosted agents — the container that runs your code. This
repo invokes it through [`python/services/api/app/foundry_agents/maf_client.py`](../python/services/api/app/foundry_agents/maf_client.py)
or [`dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs).

## Foundry Project

A resource inside Microsoft Foundry that scopes agents, model
deployments, RBAC, and observability for one workload. This repo
provisions exactly one via Terraform.

## Model deployment

A named, region-scoped deployment of a specific model (for example
`gpt-4.1-mini`) inside an Azure AI Services / Foundry account. Terraform
provisions three: `asg-chat` for the three roles, `asg-router` for the model
router, and `asg-judge` for evaluation. Per-role deployments are supported by
the env-var scheme in `python/services/api/.env.example`, which the .NET
track's `.env` (written by `dotnet/scripts/populate-env.ps1`) shares.

## Contract

The typed shape of an agent's output. Each one is a Pydantic model in
[`python/services/api/app/agents/shared/contracts.py`](../python/services/api/app/agents/shared/contracts.py)
or a record in
[`dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs)
that carries `contract_version`. A reply that does not parse into it is a
typed failure, never surfaced content.

## JSON Schema

The open specification used to describe the shape of a JSON document.
Files ending in `.schema.json` in this repo are JSON Schemas: each agent's
input and output shapes, in `agents/<id>/schemas/`. They document the agent
definition; the typed contracts above are what the app enforces.

## Eval / evaluation

A test that checks how well an agent behaves against a set of synthetic
cases. In this repo, evaluation grades answer **quality** — groundedness,
relevance and coherence — with a judge model through Agent Framework:
[`python/scripts/run_agent_evals.py`](../python/scripts/run_agent_evals.py) or
[`dotnet/scripts/run_agent_evals.cs`](../dotnet/scripts/run_agent_evals.cs) grades
the cases in [`/evals`](../evals) on demand. Structure and safety (only
allowed IDs, the human-review caveat) are not left to an eval: the
validator's deterministic checks enforce them on every request. Module 9
covers both.

## GenAIOps

The operating discipline for generative-AI workloads. Adds
prompt/spec versioning, contract versioning, safety-oriented
evaluation, and metadata-only observability on top of traditional
DevOps and MLOps. See [genaiops.md](genaiops.md).

## MLOps

The operating discipline for classical machine-learning workloads.
Manages training runs, datasets, model registries, deployments, and
monitoring. This repo does not train a model; the model is served by
Microsoft Foundry. MLOps concerns here reduce to model-version
tracking, retirement handling, and deployment binding.

## DevOps

The operating discipline for software delivery: source control,
automated builds, tests, deployments, and configuration management.
In this repo it shows up as version-controlled Terraform, documented
local commands, and lint/type/test tooling.

## Metadata-only observability

Telemetry that captures only structural information — agent name,
status code, latency, coarse error category, trace ID — and never
captures the user's text, the prompt, or the model's completion.
See [observability.md](observability.md).

## Keyless auth / DefaultAzureCredential

A pattern where the application never holds a static API key.
Instead, `DefaultAzureCredential` from `azure-identity` (Python) or
`Azure.Identity` (.NET) acquires a short-lived bearer token for the target
resource using the developer's `az login`, a managed identity, or a workload
identity. This repo uses it in
[`python/services/api/app/foundry_agents/maf_client.py`](../python/services/api/app/foundry_agents/maf_client.py)
and, through
[`Credentials.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Credentials.cs),
in [`MafClient.cs`](../dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/MafClient.cs).
The .NET credential leaves out the Visual Studio and VS Code sign-ins, so on
a laptop both tracks use your `az login` account.

## RBAC

Role-Based Access Control. Azure grants callers permission to
resources by assigning roles. This repo grants the app's principal
the `Cognitive Services OpenAI User` role at the AI Services account
scope via Terraform.

## Synthetic data

Data generated by deterministic factories seeded with a fixed constant.
Nothing on screen represents a real person, dealership, or organization.
Every dealership, KPI, and trend value in this repo is synthetic.

## Human review caveat

An explicit statement in every generated recommendation that a human
must review it before use. The Validator Agent enforces the presence
of this caveat as a hard failure. Recommendations that lack it never
leave the coordinator.

## Dealer group (`dealer_group_id`)

The tenant boundary in this repo. A string matching pattern
`^[A-Z0-9][A-Z0-9\-]{1,31}$` (for example, `GROUP-A`, `GROUP-DEMO`)
that identifies a dealer group. Required on every request,
propagated to every agent, stamped on every payload, and enforced by
Validator Agent checks (`DRAFT_DEALER_GROUP_MISMATCH`,
`CROSS_DEALER_GROUP_CITATION`). In target production, each dealer group maps
to its own Microsoft Fabric workspace and lakehouse. See
[`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md).

## Citation

A typed reference to a source that grounds a recommendation. Includes
`citation_id`, `dealer_group_id`, `source_type` (structured_data,
document, policy, resource, synthetic_fixture), `source_title`,
`section_or_page`, `evidence_summary`, `source_ref`, `retrieved_at`,
and `confidence`. Never contains the raw document body. Defined as
`Citation` in
[`python/services/api/app/agents/shared/contracts.py`](../python/services/api/app/agents/shared/contracts.py)
and
[`dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs`](../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Contracts.cs).

## Evidence bundle

The result of a call to
[`EvidenceRetriever.retrieve(...)`](../python/services/api/app/evidence/retrieval.py)
([`IEvidenceRetriever.RetrieveAsync(...)`](../dotnet/services/api/AgenticSupportGuide.Api/Evidence/Retrieval.cs)
in .NET).
Carries a `dealer_group_id` and a collection of `Citation` items scoped
to that dealer group. Attached to the Support Recommendation Agent's
context; consumed by the Validator Agent to verify citation
integrity. See
[`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md).

## Human review state

The lifecycle field on each recommendation: `draft`, `pending_review`,
`approved`, or `rejected`. Transitions are enforced in
[`python/services/api/app/human_review.py`](../python/services/api/app/human_review.py)
and
[`dotnet/services/api/AgenticSupportGuide.Api/HumanReview.cs`](../dotnet/services/api/AgenticSupportGuide.Api/HumanReview.cs):
`draft -> pending_review`, `pending_review -> approved|rejected`,
`rejected -> pending_review`. `approved` is terminal. Transitions
happen through `POST /api/supports/plans/{plan_id}/review` and are
audited.

## Correlation ID

A UUID4 string generated by the coordinator per
request and stamped on every envelope, audit row, and
review-transition record. Used to trace a single
recommendation end-to-end without exposing prompts or completions.
It is **not** exported as a span attribute, so you cannot search
Application Insights by it.
See [`observability.md`](observability.md).

## Support Recommendation Agent

The remote Foundry agent that proposes multi-tier supports for a
dealership concern. It cites retrieved evidence and cannot approve its
own output; the Validator Agent decides whether a draft is returned.
