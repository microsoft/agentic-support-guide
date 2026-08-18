# ADR 0001 - Agent hosting

Status: Accepted
Date: 2026-01-05

## Context

The `agentic-support-guide` prototype needs three collaborating agents
backed by Azure AI Foundry model deployments:

- Data Analyst Agent
- Support Recommendation Agent
- Validator Agent

We needed to choose between:

1. Hosting each agent as a Microsoft Agent Framework / Azure AI Foundry
   hosted agent, orchestrated via a Foundry hosted workflow.
2. Implementing each agent as a small local Python class inside the
   FastAPI service, orchestrated by a local `AgentCoordinator`, with the
   LLM calls going to an Azure AI Foundry model deployment.

## Decision

Use option 2 for this iteration: local Python agent classes backed by an
Azure AI Foundry model deployment.

## Rationale

- The Azure OpenAI Python SDK plus `azure-identity`
  `DefaultAzureCredential` supports keyless chat completions against an
  Azure AI Services account today. This is the stable, documented path
  for calling an Azure AI Foundry model deployment programmatically.
- Foundry hosted agent definitions are data-plane objects; there is no
  stable `azurerm_*` Terraform resource for them today. Baking them into
  the demo would make Terraform brittle.
- Local orchestration keeps the coordinator, prompt-injection defenses,
  deterministic validation, and repair loop entirely within our
  test-controlled process. This makes hermetic pytest coverage possible.
- The typed contracts in `agents/shared/contracts.py` and the coordinator
  boundary let each agent migrate to a Foundry hosted agent later
  without changing consumer code.

## Consequences

- The prototype uses one Azure resource path
  (`azurerm_cognitive_deployment` on a Foundry-enabled AI Services
  account) instead of a Foundry hosted-agent path.
- We document the migration path in
  [`../future-azure-architecture.md`](../future-azure-architecture.md).
- The `AzureFoundryLlmProvider` is still Foundry-first in naming and
  documentation because it calls a model deployed inside a Foundry
  project.
