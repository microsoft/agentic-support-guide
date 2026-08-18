# Future Azure architecture

The three-agent workflow, contracts, coordinator, and Azure AI Foundry
model deployment are implemented today. This document describes future
production hardening. None of the items below are implemented in this
build.

## Independent deployment of the implemented agents

The `agents/data_analyst`, `agents/support_recommender`, and
`agents/validator` packages already have narrow typed interfaces and no
cross-imports. Future work could extract each into its own container,
Azure Container App, or Azure Function, with the coordinator either
remaining a client-side orchestrator (Azure Container Apps job or a
Microsoft Agent Framework hosted workflow) or migrating to a Foundry
hosted workflow.

## Durable workflow state

The coordinator is stateless today. Future production could persist
per-request workflow state (analysis output, draft, validator report,
repair attempts) using:

- Azure Storage table/blob, or
- Azure Cosmos DB, or
- Microsoft Fabric warehouse for analytics on completed workflows.

## Entra-secured APIs

- Introduce Microsoft Entra ID authentication on the FastAPI service.
- Introduce Azure API Management (APIM) in front for throttling,
  request-based routing, and per-consumer keys.
- Replace the placeholder `Staff S-01` identity with the Entra ID claim
  set from the caller.

## Fabric-backed data access

- Replace the seeded synthetic repositories with Microsoft Fabric
  lakehouse or warehouse queries.
- Model each domain (learners, assessments, behavior, supports) as a
  semantic model / Direct Lake dataset.
- Use Microsoft Graph and Microsoft 365 Copilot connectors where
  appropriate to pull authorized organizational context.
- Use Microsoft IQ-style grounding concepts - work signals, business
  context, relationship context, semantic data layers, governed domain
  context - to enrich agent inputs without exceeding user scopes.

## Azure AI Foundry hosted-agent migration

Once stable SDK/API support for Foundry hosted agents is available and
the workflow scales beyond what one coordinator can manage, migrate the
three agents to Foundry hosted agent definitions:

- Move prompt templates and structured output schemas into the Foundry
  project.
- Route requests through Foundry's evaluation and safety workflows.
- Keep the deterministic Validator logic in code; only the LLM critique
  path would move to Foundry.

## Governance

- Microsoft Purview for data catalog, lineage from Fabric through
  Foundry to the API, and policy enforcement.
- Azure Policy for platform-level guardrails on Foundry regions, allowed
  models, and networking.

## Hosting

- Azure App Service or Azure Container Apps for independently deployable
  frontend and API.
- Static Web Apps for the frontend if a global CDN is preferred.
- Azure Container Apps jobs for background workflow steps.

## Secrets and configuration

- Azure Key Vault for any future non-model secrets, mounted via managed
  identity. Model keys remain unnecessary because keyless auth is the
  primary path.

## Observability

- Application Insights + Azure Monitor already integrated in Terraform.
- Add distributed tracing spans on the coordinator and each agent step.
- Ship telemetry to a Log Analytics workspace shared with Fabric for
  cross-domain analysis.

## CI/CD

- Azure DevOps Pipelines or GitHub Actions per component:
  - Frontend: build, test, publish to Static Web Apps or Container Apps.
  - Backend: ruff / mypy / pytest / container build / deploy.
  - Infra: `terraform fmt / init / validate / plan`; apply gated on
    approvals.

## Deployment modes

- Embedded module experience: the frontend and API are embedded in a
  larger admin console via iframe or module federation.
- Standalone experience: the frontend and API are deployed side by side
  with their own domain and auth.

Neither mode is implemented in this build.
