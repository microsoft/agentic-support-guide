# Agents

This folder is the **target source-of-truth for agent configuration**.
It is intentionally protocol- and configuration-only: no Python
implementation lives here.

Today, the FastAPI backend at [`services/api/`](../services/api/) still
loads specs from `services/api/app/agents/specs/` because the runtime
demo path uses that loader. This folder is the migration target: the
manifests, agent.md files, and schemas below are the definitions we
plan to move to as the runtime seam.

## Layout

```
/agents/
  <agent-name>/
    agent.md          # human-readable instructions (source of truth)
    manifest.yaml     # runtime metadata (spec version, model, contracts)
    schemas/
      input.schema.json
      output.schema.json
    tests/
      <optional agent-scoped tests>
```

- `agent.md` is the source of truth for the human-readable instructions
  the LLM receives.
- `manifest.yaml` is the source of truth for **runtime metadata**:
  which model deployment to call, the schema contract versions, the
  handoff targets, and safety policy references.
- `schemas/input.schema.json` and `schemas/output.schema.json` describe
  the **agent-local** payloads. Cross-agent messages live in
  [`/contracts/v1/`](../contracts/v1/).
- `tests/` holds agent-scoped tests that do not require the FastAPI
  runtime.

## Source-of-truth rules

- `agent.md` is authoritative for prompt content. Python must not
  duplicate role-specific prompt text.
- `manifest.yaml` is authoritative for runtime metadata: model
  deployment name, timeouts, output-format hints, contract versions.
- `/contracts/v1/*.schema.json` is authoritative for **inter-agent**
  messages. Compatibility rules are documented in
  [`/contracts/README.md`](../contracts/README.md).

## Migration status

- [x] Spec content lives here as `agent.md` per agent.
- [x] Manifests present with contract references and model bindings.
- [x] Schemas present.
- [ ] Runtime adapter loads from this folder. **Not yet.** The current
      runtime loader in `services/api/app/agents/specs/loader.py`
      continues to be the source until the adapter is switched. See the
      *"Post-demo migration"* section below.

## Post-demo migration

Once the demo has run and the app is stable:

1. Introduce `LocalManifestAgentAdapter` in
   `services/api/app/agents/adapter.py` that:
   - reads `manifest.yaml` for a given agent name,
   - resolves `agent.md` alongside it,
   - loads referenced contract schemas from `/contracts/v1/`,
   - constructs the same rendered system prompt the existing
     `render_system_prompt(spec)` helper produces,
   - hands off to the existing `AzureFoundryLlmProvider`.
2. Swap the three agent classes to consume `LocalManifestAgentAdapter`
   instead of the existing loader.
3. Delete `services/api/app/agents/specs/` and its README.
4. Introduce `FoundryHostedAgentAdapter` only when the pinned openai +
   azure-identity + Foundry SDK versions clearly support hosted-agent
   CRUD.

## What must never appear here

- Real customer, partner, vendor, or product names.
- Real learner, staff, or personnel names.
- Real school, district, organization, meeting, or source-document
  names.
- Real email addresses (only `@example.invalid` is permitted anywhere
  in the repo).
- Any URL not in the scanner's Microsoft/Azure allowlist or
  `example.invalid`.
