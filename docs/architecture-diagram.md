# Architecture diagram

The high-level C4 container view for **Agentic Support Guide** lives in
[`architecture.dsl`](architecture.dsl) as a Structurizr DSL model.

## What it shows

- One person (`Demo User`) and one internal system (`Agentic Support Guide`)
  with five containers: `Web App`, `API Service`, `Synthetic Data`,
  `Agent Definitions`, and `Protocol Contracts`.
- One external system `Azure AI Foundry` with `Foundry Project`,
  `Remote Foundry Agents`, `Model Deployment`, and `Observability`.
- One external system `Operations` with `Terraform and Scripts`.

The three role agents (Data Analyst, Support Recommendation, Validator)
are represented as a single `Remote Foundry Agents` container. The API
Service performs deterministic orchestration in application code; there
is no fourth "coordinator agent" in the model.

## Viewing

- Open `architecture.dsl` with a Structurizr DSL VS Code extension for
  inline rendering.
- Or paste the file contents into a Structurizr Lite instance to render
  the container view.

The Container view is named `AgenticSupportGuideContainers` and uses
`autoLayout lr`.

## Scope

This diagram is intentionally high-level and customer-safe. It omits
sequence-level detail, per-request arrows, and internal wiring on
purpose. For runtime protocol and orchestration detail, see
[`architecture.md`](architecture.md) and
[`adr/0001-agent-hosting.md`](adr/0001-agent-hosting.md).
