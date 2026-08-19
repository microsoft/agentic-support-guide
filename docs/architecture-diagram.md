# Architecture diagram

A high-level C4 container view of **Agentic Support Guide** that is
safe to show in a customer demo. The diagram intentionally omits
sequence detail; see [`architecture.md`](architecture.md) for runtime
and protocol notes.

## Diagram workflow

- The **editable source** is [`architecture.dsl`](architecture.dsl), a
  Structurizr DSL model of the container view.
- The **GitHub-rendered artifact** is `architecture.svg`, produced by
  exporting `architecture.dsl` with Structurizr-compatible tooling and
  committing the result. GitHub renders SVG inline in Markdown; it
  does not render Structurizr DSL directly.

## Rendered diagram

> `docs/architecture.svg` is not committed yet. Export it from
> `docs/architecture.dsl` with Structurizr-compatible tooling and
> commit the result. Once the file exists at `docs/architecture.svg`,
> GitHub will render it inline anywhere it is embedded with an
> `<img>` tag.

## Viewing and editing the DSL

- Open [`architecture.dsl`](architecture.dsl) with a
  Structurizr-compatible editor (for example, a Structurizr DSL VS
  Code extension) to preview and edit the model inline.
- Or load the file into a Structurizr Lite instance to render the
  Container view named `AgenticSupportGuideContainers`.

## Exporting to SVG

No SVG export command is documented in this repository. Use any
Structurizr-compatible tool to export `docs/architecture.dsl` to
`docs/architecture.svg`, then commit the SVG so GitHub can render it.

## Regenerate when the DSL changes

Whenever `architecture.dsl` changes, regenerate `architecture.svg`
and commit both files together. Reviewers can then diff the DSL and
see the rendered result in the same PR.

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
