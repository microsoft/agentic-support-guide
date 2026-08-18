# Security and privacy

The prototype is designed so that no real learner, staff, customer, or
partner data can leak through the LLM or through logs.

## Data boundary

- All data used in the demo is generated in-memory from deterministic
  factories seeded with `SEED = 20260101`.
- No database, no persistent storage, no external ingestion.
- User-provided concern text is treated as untrusted data.

## Agent-to-agent boundary

- The three agents exchange messages only through frozen Pydantic
  contracts in `agents/shared/contracts.py`.
- No agent imports another agent's implementation module.
- The `AgentCoordinator` is the only place that sequences agents.
- Each shared message includes `contract_version` and is schema-validated
  before being forwarded.

## Prompt-injection handling

- Free-text user input is sanitized (`sanitize_free_text`): control chars
  stripped, common injection phrases replaced with `[filtered]`, delimiter
  tags removed, whitespace collapsed, and length clipped to 1000 chars.
- Every untrusted block is wrapped in
  `<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` tags.
- System prompts instruct the model to treat wrapped blocks as data only.
- Prior-agent outputs are also passed as untrusted blocks so a
  compromised or hallucinated upstream cannot inject instructions
  downstream.
- Validator repair guidance sent back to the recommender is drawn from
  fixed templates, not from raw LLM critique text.

## No prompt or completion logging

- Telemetry captures metadata only: agent name, status, provider, model,
  latency, token estimate, error category.
- The `TelemetryRecorder` denylist rejects unsafe keys
  (`prompt`, `completion`, `concern_text`, `raw_critique`, `secret`,
  `api_key`, `token`).
- The audit endpoint returns seeded synthetic rows plus in-memory
  metadata rows. It never returns prompts, completions, raw validator
  critique, or secrets.

## Keyless auth

- `AzureFoundryLlmProvider` uses `DefaultAzureCredential` from
  `azure-identity` and requests bearer tokens for
  `https://cognitiveservices.azure.com/.default`.
- Terraform sets `local_auth_enabled = false` on the AI Services account
  and never reads model keys. No key is written to Key Vault.
- The backend expects RBAC assignments (`Cognitive Services OpenAI User`
  and `Azure AI User`) provisioned by Terraform.

## Secret handling

- `.env` and `terraform.tfvars` are gitignored.
- `.env.example` and `terraform.tfvars.example` contain placeholder
  names only.
- Application Insights connection string is marked `sensitive = true`
  in Terraform outputs.
- The privacy scanner test flags any 32+ character base64/hex value on a
  line that begins with `AZURE_*=`.

## Validation gates

- Every LLM response is parsed and Pydantic-validated against a typed
  contract before flowing forward.
- The Validator Agent enforces deterministic rules: allowed resource ids,
  allowed SMART goal ids, allowed strategy ids, required caveats,
  required tier framing, required progress-monitoring measures, and
  contract version match.
- If validation still fails after one repair pass, no recommendation is
  returned; the API returns a typed `validation_failed` envelope with
  safe issue codes.

## Human review

Every generated recommendation includes explicit caveats requiring human
review before any use, and the UI shows a persistent prototype banner.

## Content filter handling

- The provider layer classifies content-filter responses and raises
  `LlmError("content_filter", ...)`.
- The coordinator maps that to a `provider_content_filter` status code.
- The UI shows a distinct safe state for content-filter blocks with no
  raw model text.

## What the prototype is not

- Not a real AI-safety review pipeline.
- Not a substitute for human review.
- Not a medical, legal, disability, placement, or compliance
  determination system.
