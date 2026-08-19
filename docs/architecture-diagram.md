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

The most recent DSL revision added:

- `Evidence Retriever` (with `EvidenceRetriever` interface, fixture
  implementation today, Fabric-backed intended for production).
- `Human Review` (lifecycle: draft → pending → approved / rejected).
- `Microsoft Fabric (per district)` external system with a
  workspace + lakehouse container per district.
- Cross-references to the new ADRs.

These are reflected in the SVG's accessible description text
(`<desc>`), but the visual layout has not been redrawn to add the new
boxes. When the operator installs the render toolchain, running
`./scripts/render-architecture-diagram.ps1` will regenerate the SVG
from the current DSL.

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
  `RemoteFoundryAgentsComponents`).

## What the diagram shows

- One person: `Demo User`.
- One internal software system, `Agentic Support Guide`, with seven
  containers (`Web App`, `API Service`, `Synthetic Data`,
  `Evidence Retriever`, `Human Review`, `Protocol Contracts`,
  `Agent Definitions`) plus one C4 component nested inside
  `API Service`: `Workflow Coordinator`.
- One external software system, `Azure AI Foundry`, with four
  containers (`Foundry Project`, `Remote Foundry Agents`,
  `Model Deployment`, `Observability`) plus three C4 components nested
  inside `Remote Foundry Agents`: `Data Analyst Agent`,
  `Support Recommendation Agent`, and `Validator Agent`.
- One external software system, `Microsoft Fabric (per district)`,
  with a workspace + lakehouse container per district (shown as
  `District A workspace + lakehouse` and `District B workspace +
  lakehouse`). This tier is the **target production data plane**;
  this repo talks to it via the `Evidence Retriever` abstraction, and
  today only the synthetic fixture implementation is wired up.
- One external software system, `Deployment & Operations`, with one
  container: `Terraform & Sync Scripts`.

The three remote agents share a single `Model Deployment`, shown by one
grouped arrow labeled *uses shared model deployment* rather than three
separate connections.

The Fabric workspace-per-district boundary reflects the district
isolation rule (see
[`adr/0003-district-isolation-and-grounding.md`](adr/0003-district-isolation-and-grounding.md)).
The `Evidence Retriever` container is the plug-in point for a
Fabric-backed retriever (see
[`adr/0004-grounding-and-citations.md`](adr/0004-grounding-and-citations.md)).
The `Human Review` container reflects the draft / pending / approved
/ rejected lifecycle enforced by the coordinator and the review
endpoint.
