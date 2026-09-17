# Inter-agent contracts

This folder holds the versioned JSON Schemas used at the **agent
boundary**. Agents exchange messages that validate against these
schemas. Local runtime type stubs may exist inside
`services/api/app/`, but the schemas here are the source of truth.

## Versioning

- Each schema carries a `schema_version` field and a `payload` block.
- Compatibility rules live in the [Compatibility policy](#compatibility-policy) below.

## Envelope shape

Every message across an agent boundary looks like:

```json
{
  "schema_version": "1.0.0",
  "message_id": "uuid",
  "trace_id": "uuid",
  "created_at": "2026-01-05T09:00:00Z",
  "source_agent": "data-analyst-agent",
  "target_agent": "support-recommendation-agent",
  "payload": { ... },
  "metadata": { ... }
}
```

- `message_id` is per-message.
- `trace_id` is per-workflow-run and shared across the three agent hops.
- `payload` is the schema-validated business content.
- `metadata` may include safe metrics (latency_ms, token_estimate).

## Files

| Schema | Purpose |
| --- | --- |
| `data-analysis-request.schema.json` | Coordinator → Data Analyst Agent. |
| `data-analysis-result.schema.json` | Data Analyst Agent → downstream. |
| `support-recommendation-request.schema.json` | Coordinator → Support Recommendation Agent. |
| `support-recommendation-result.schema.json` | Support Recommendation Agent → downstream. |
| `validation-request.schema.json` | Coordinator → Validator Agent. |
| `validation-result.schema.json` | Validator Agent → coordinator. |
| `agent-trace.schema.json` | Per-step trace record surfaced to the UI. |

## Compatibility policy

- **Non-breaking (additive):** adding a new optional field, adding an
  enum value where consumers are permissive, expanding a `maxLength`.
  Bump the schema patch or minor version.
- **Breaking:** removing a required field, renaming a required field,
  removing an enum value that any consumer requires, tightening a
  `maxLength`, changing a field type. Bump the schema major version and
  publish alongside the old major for a deprecation window.
- **Runtime enforcement:** the adapter must reject a message whose
  `schema_version` does not match the adapter's expected major.

## Safety rules baked into the contracts

- All free-text fields carry `maxLength` constraints (typically 300 for
  bullets, 500 for short strings, 2000 for a rationale, 1000 for the
  concern text).
- `source_type` is a closed enum. Support tier and category are
  constrained in prose and checked by the validator rather than by the
  schema, so that the allowed catalog can change without a contract bump.
- `issue_codes` and `warning_codes` fields enforce the pattern
  `^[A-Z][A-Z0-9_]{3,59}$`. Free-text critique from an LLM is stripped
  by the runtime before it can reach these fields (see
  `services/api/app/agents/shared/prompt_blocks.py`).
- Every message that ships to the UI or audit trail must have already
  passed schema validation once. If validation fails, the coordinator
  returns a safe typed error and no payload content.

## Never in these files

- Real customer, partner, vendor, or product names.
- Real dealership, staff, or personnel names.
- Real email addresses (only `@example.invalid` is permitted).
- Any URL not in the scanner's Microsoft/Azure allowlist or
  `example.invalid`.

The privacy scanner in
[`services/api/tests/scanner.py`](../services/api/tests/scanner.py)
scans this folder along with the rest of the repo.
