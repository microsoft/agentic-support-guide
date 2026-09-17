# Architecture diagram

A customer-safe, high-level view of **Agentic Support Guide**. It shows
the three remote Foundry agents as separate visible components and keeps
the diagram uncluttered by C4 metadata jargon.

## Rendered diagram

<p align="center">
  <img src="architecture.svg" alt="High-level architecture diagram" width="900" />
</p>

## About the Workflow Coordinator

The **Workflow Coordinator** shown nested inside the API Service is
**deterministic service-side code**, not a fourth agent. It is regular
Python inside the FastAPI service that:

- sequences the three remote agents in a fixed order,
- validates every inter-agent message against a JSON Schema in
  [`/contracts/v1`](../contracts/v1),
- enforces per-run and total budgets,
- runs a single, bounded repair pass if the Validator Agent rejects
  the draft.

All reasoning happens inside the three remote agents in Azure AI
Foundry. The coordinator does not talk to a language model and does not
appear as an assistant in Foundry.

## Files that make up the diagram

- [`architecture.dsl`](architecture.dsl) — the **semantic source model**
  in Structurizr DSL. This is where the containers, components, and
  relationships are declared.
- [`architecture.svg`](architecture.svg) — the **GitHub-rendered
  companion image**. It is currently a hand-maintained SVG that mirrors
  the DSL model.
- [`../scripts/render-architecture-diagram.ps1`](../scripts/render-architecture-diagram.ps1)
  — regeneration helper. It shells out to `structurizr-cli` and
  `plantuml` if both are on `PATH`, or exits with a clear installation
  hint if they are not.

## Regeneration status

The current `architecture.svg` was **not** produced by running the
render script. No repo-local Structurizr export chain is installed, so
the SVG is a hand-maintained companion diagram that matches the DSL by
convention.

When the DSL changes, the operator should either:

1. install `structurizr-cli` and `plantuml`, then run
   `./scripts/render-architecture-diagram.ps1`, or
2. hand-edit `architecture.svg` to match the new DSL and commit both
   files together.

The SVG is valid XML/SVG, uses a white background, contains no scripts,
no external images, no external fonts, no `foreignObject`, and no
endpoints, IDs, secrets, or local paths.

## C4 element-type labels

Standard Structurizr exports include labels like `[Container: FastAPI]`
or `[Person]` next to each element. Those are helpful for architects but
distracting in a customer demo. The current hand-maintained SVG omits
them intentionally. If the operator switches to a real Structurizr
export later, they may reappear; suppression depends on the export tool
in use and is not currently applied in the DSL styles.

## Editing the DSL directly

- Open [`architecture.dsl`](architecture.dsl) with a Structurizr-
  compatible editor (for example, a Structurizr DSL VS Code extension)
  to preview the model interactively while editing.
- Or load the file into a Structurizr Lite instance to render the
  Container view named `AgenticSupportGuideContainers` or the two
  Component views (`APIServiceComponents`,
  `EphemeralFoundryAgentsComponents`).

## What the diagram shows

- One person: `Demo User`.
- One internal software system, `Agentic Support Guide`, with six
  containers (`Web App`, `API Service`, `Synthetic Data`,
  `Human Review`, `Agent Definitions`, `Protocol Contracts`) plus one
  C4 component nested inside `API Service`: `Workflow Coordinator`.
- One external software system, `Azure AI Foundry`, with four
  containers (`Foundry Project`, `Ephemeral Foundry Agents`,
  `Model Deployment`, `Observability`) plus three C4 components nested
  inside `Ephemeral Foundry Agents`: `Data Analyst Agent`,
  `Support Recommendation Agent`, and `Validator Agent`.
- One external software system, `Deployment & Operations`, with one
  container: `Terraform & Ops Scripts`.

`Ephemeral Foundry Agents` describes the runtime: instructions are composed
in-process per call, so the application never invokes a stored agent. The
same definitions are separately published to Foundry as versioned prompt
agents for portal visibility — see
[`adr/0006-published-prompt-agents.md`](adr/0006-published-prompt-agents.md).

The three agents share a single `Model Deployment`, shown by one
grouped arrow labeled *uses shared model deployment* rather than three
separate connections.

The dealer group isolation rule is enforced in the API and the retrieval
filter rather than by a container boundary (see
[`adr/0003-dealer-group-isolation-and-grounding.md`](adr/0003-dealer-group-isolation-and-grounding.md)
and
[`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)).
The `Human Review` container reflects the draft / pending / approved
/ rejected lifecycle enforced by the coordinator and the review
endpoint.
