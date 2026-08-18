# ADR 0001 - Foundry project Terraform choices

Status: Accepted
Date: 2026-01-05
Provider: `hashicorp/azurerm` `>= 4.40.0, < 5.0.0`
Terraform: `>= 1.9.0`

## Context

Terraform in `/infra` must deploy the minimum Azure AI Foundry resources
needed for real LLM calls from the three implemented agents.

## Decision

Use the current `azurerm_cognitive_account` +
`azurerm_cognitive_account_project` + `azurerm_cognitive_deployment`
combination, plus workspace-based Application Insights.

### Resource choices

- **AI Services account**: `azurerm_cognitive_account`
  - `kind = "AIServices"`
  - `sku_name = "S0"`
  - `project_management_enabled = true`
  - `custom_subdomain_name` set (required for keyless auth)
  - `local_auth_enabled = false`
  - `public_network_access_enabled = true` for this demo
  - `identity { type = "SystemAssigned" }`
- **Foundry project**: `azurerm_cognitive_account_project`
  - Attached to the AI Services account.
  - Requires `identity` block; SystemAssigned selected.
  - Exposes `endpoints` map used only for observability today.
- **Model deployment**: `azurerm_cognitive_deployment`
  - Attached to the AI Services account (not the project).
  - `model.format = "OpenAI"`, `name = var.model_name`,
    `version = var.model_version`.
  - `sku.name = var.model_sku_name` (`DataZoneStandard` by default,
    which keeps inference traffic inside a single Azure data zone),
    `sku.capacity = var.model_capacity`.
  - `location` has no default; the operator must provide it via
    `terraform.tfvars` or `-var`. This forces an explicit region
    decision because model availability, SKU support, and quota are
    region-dependent.
- **Observability**: `azurerm_log_analytics_workspace` +
  `azurerm_application_insights` (workspace-based). Not a dependency of
  the Foundry project.

### Provider version

`azurerm_cognitive_account_project` requires a recent azurerm provider.
This project pins `>= 4.40.0, < 5.0.0`. The lock file
(`.terraform.lock.hcl`) is committed to ensure provider reproducibility.
Standard setup uses plain `terraform init`, which respects the lock file.
`terraform init -upgrade` is used only when the maintainers deliberately
refresh providers within the pinned range, followed by re-running
`terraform validate` and `terraform plan` before committing the new lock.

### Endpoint used by the backend

- The backend `AzureFoundryLlmProvider` calls the AI Services
  `endpoint` (`azurerm_cognitive_account.endpoint`) for chat completions.
- `foundry_project_name` and `foundry_project_endpoints` are exposed as
  outputs and read into `.env` for observability and future
  project-scoped SDK routing.
- Project-scoped chat routing is not active in this iteration because
  the openai + azure-identity SDK path used here consumes the AI
  Services endpoint. This is documented in
  [`0001-agent-hosting.md`](./0001-agent-hosting.md).

### Rejected alternatives

- `azurerm_ai_foundry`, `azurerm_ai_foundry_project`: represent the
  classic `Microsoft.MachineLearningServices` hub path. Not compatible
  with the new Foundry project experience required by this project.
- Inventing `azurerm_ai_project` or Foundry-hosted-agent resources: not
  a stable resource type. Rejected.
- Shelling out to `az` from Terraform: rejected.
- Storing model keys in Key Vault: rejected. Keyless auth is primary.

## Consequences

- The prototype is Foundry-first in naming, environment variables, and
  documentation.
- Terraform state may contain resource metadata and must never be
  committed.
- RBAC role assignments (`Cognitive Services OpenAI User` and
  `Azure AI User`) can take several minutes to propagate. First-run
  inference may briefly return 401/403.
- No manual follow-up is required after a successful
  `terraform apply` other than populating `.env` from the outputs (see
  the infra README).
