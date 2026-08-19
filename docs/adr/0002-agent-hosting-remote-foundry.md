# ADR 0002 - Agent hosting: remote Azure AI Foundry Agent Service

Supersedes: [0001-agent-hosting.md](0001-agent-hosting.md)
Status: Accepted
Date: 2026-08-19

## Context

The prototype needs three collaborating agents backed by Azure AI
Foundry.

Two options considered:

1. **Remote agents in Azure AI Foundry Agent Service.** Each of the
   three roles is defined once in the repo (`/agents/<id>/agent.md`
   + `manifest.yaml`) and provisioned into Foundry as a remote agent
   via the `azure-ai-agents` SDK. The FastAPI service orchestrates the
   sequence by invoking each remote agent through
   `FoundryRemoteAgentAdapter` and enforcing the wire protocol at
   every hop.
2. **Local Python runtime calling a shared model deployment.** Each
   role is a Python class that loads `agent.md`/`manifest.yaml`
   through a `LocalManifestAgentAdapter` and calls the same Azure AI
   Foundry model deployment directly via the OpenAI-compatible Chat
   Completions surface. No remote agents exist.

## Decision

**Option 1.** Every recommendation request is served by three remote
Foundry agents. The application code does not call the base model
directly and does not fall back to a local runtime.

- Role instructions live in `/agents/<id>/agent.md` (source of truth).
- Runtime metadata + Foundry binding hints live in
  `/agents/<id>/manifest.yaml` (see the `foundry:` block).
- Inter-agent protocol lives in `/contracts/v1/*.schema.json` and is
  validated by
  [`services/api/app/contracts_registry.py`](../../services/api/app/contracts_registry.py).
- Remote agents are created/updated by
  [`scripts/sync_foundry_agents.py`](../../scripts/sync_foundry_agents.py),
  which composes runtime instructions = `agent.md` body + a fixed
  generic envelope and writes assistant IDs to
  `.foundry/agent-bindings.local.json` (gitignored). A committed
  example lives at `.foundry/agent-bindings.example.json`.
- The three Python role classes (`DataAnalystAgent`,
  `SupportRecommendationAgent`, `ValidatorAgent`) invoke the remote
  agents through
  [`FoundryRemoteAgentAdapter`](../../services/api/app/foundry_agents/adapter.py).
  The role-specific input construction (untrusted-data delimiters,
  sanitization) stays in Python; the model behavior is entirely
  configured on the remote agent.

## Rationale

- Option 1 puts prompt and model configuration in one place — the
  remote agent object in Foundry — so changes are traceable and
  observable in the Foundry UI.
- Option 2 duplicates prompt state (both `agent.md` and whatever
  temperature/format overrides the SDK client sends per call) and
  makes it easy for direct model calls to slip past the wire
  protocol.
- The application still runs the *orchestration*, since Foundry does
  not yet expose a first-class workflow resource that captures our
  deterministic sequence + protocol enforcement + one-shot repair
  loop as declaratively as we need. The coordinator remains
  deterministic Python; it is not a fourth agent.
- Connected Agents / agent-as-tool patterns are deliberately not used
  in this build. Handoffs are explicit HTTP round trips validated by
  the contracts registry.

## Constraints enforced by the design

- Agents do not contain runtime Python implementation. Anything under
  `/agents/<id>/` is configuration only.
- Agents do not import each other.
- Agents do not import API internals.
- No Python file (other than
  `services/api/app/foundry_agents/sdk_client.py`) may import
  `azure.ai.agents`, `AzureOpenAI`, `openai.`, or reference
  `chat.completions`.
- The contracts registry enforces protocol at every hop; the
  coordinator returns a typed `invalid_model_json` /
  `PROTOCOL_VALIDATION_FAILED` result if any hop fails.
- No runtime mock-LLM mode exists. Tests use injected fake Foundry
  clients only. There is no local fallback to the base model.
- Bindings are refused when the configured project endpoint does not
  match the endpoint that produced them, unless the operator passes
  `--rebind` explicitly. This prevents accidental cross-environment
  use of an assistant ID.

## Consequences

- Deploying a new environment now requires three steps: run Terraform,
  populate `services/api/.env` with `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
  (plus per-role `FOUNDRY_MODEL_DEPLOYMENT_*` names), then run
  `scripts/sync_foundry_agents.py --apply`. The health endpoint
  reports `foundry_project_configured`, `foundry_agents_bound`, and
  `service_side_remote_workflow_active` to make the state explicit.
- Runtime observability includes `spec_version` per agent step, so
  Application Insights queries can bucket outcomes by agent version.
- Editing `/agents/<id>/agent.md` or `manifest.yaml` changes behavior
  on the next `--apply` run. The `instructions_hash` field in the
  bindings file detects drift.
- Because remote agents own their own generation config, per-run
  overrides (temperature, response format) are deliberately not
  supported from Python. Change the remote agent instead.

## Alternatives considered

- **Foundry Connected Agents / agent-as-tool.** Rejected for this
  iteration because we need deterministic ordering + protocol
  validation + a single-shot repair loop, all with explicit failure
  codes visible to the UI. Connected agent tools make the control
  flow implicit.
- **A single Foundry workflow resource.** Not universally available in
  the current SDK surface, and coupling ordering to Foundry means the
  test suite can no longer exercise the sequence with a fake client.

## Migration notes

If the current Foundry SDK later exposes a first-class workflow
resource that captures our sequence + protocol + repair behavior, we
can move orchestration inside Foundry and reduce the coordinator to a
thin submitter. The contract schemas in `/contracts/v1` are the
migration boundary; nothing in that folder assumes local orchestration.
