# Architecture diagram

A high-level C4 container view of **Agentic Support Guide** that is
safe to show in a customer demo. The diagram intentionally omits
sequence detail; see [`architecture.md`](architecture.md) for runtime
and protocol notes.

## Rendered diagram

<p align="center">
  <img src="architecture.svg" alt="High-level architecture diagram" width="900" />
</p>

## Files that make up the diagram

- [`architecture.dsl`](architecture.dsl) — the **editable source** in
  Structurizr DSL.
- [`architecture.svg`](architecture.svg) — the **rendered GitHub image**
  embedded above and in the root [README](../README.md).
- [`../scripts/render-architecture-diagram.ps1`](../scripts/render-architecture-diagram.ps1)
  — the regeneration helper. Run it after changing the DSL so the
  committed SVG stays in sync.

## Regenerating the SVG

When `architecture.dsl` changes, regenerate the SVG:

```powershell
.\scripts\render-architecture-diagram.ps1
```

The script prefers `structurizr-cli` on the operator's PATH and uses
PlantUML to convert the intermediate `.puml` file to SVG. If either
tool is missing, the script exits with a clear installation hint and
leaves the committed `architecture.svg` untouched, so GitHub still
renders the current version.

Commit both `architecture.dsl` and `architecture.svg` in the same PR
so reviewers can diff the DSL and see the rendered result together.

## Editing the DSL directly

- Open [`architecture.dsl`](architecture.dsl) with a Structurizr-
  compatible editor (for example, a Structurizr DSL VS Code extension)
  to preview the model interactively while editing.
- Or load the file into a Structurizr Lite instance to render the
  Container view named `AgenticSupportGuideContainers`.

## What the diagram shows

- One person: `Demo User`.
- One internal system, `Agentic Support Guide`, with five containers:
  `Web App`, `API Service`, `Synthetic Data`, `Agent Definitions`,
  `Protocol Contracts`.
- One external system, `Azure AI Foundry`, with `Foundry Project`,
  `Remote Foundry Agents`, `Model Deployment`, and `Observability`.
- One external system, `Operations`, with `Terraform and Scripts`.

The three role agents are represented as a single
`Remote Foundry Agents` container. The API Service performs
deterministic orchestration; the coordinator is not a fourth agent
and does not appear as a separate container.
