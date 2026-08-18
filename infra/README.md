# Infra - Terraform for agentic-support-guide

Provisions the minimum Azure AI Foundry resources needed for real LLM
calls from the three implemented agents:

- Azure resource group.
- Azure AI Services account (`kind = "AIServices"`, `project_management_enabled = true`).
- Azure AI Foundry project (`azurerm_cognitive_account_project`).
- Model deployment (`azurerm_cognitive_deployment`, `format = "OpenAI"`).
- Log Analytics workspace + Application Insights (metadata / telemetry).
- RBAC role assignments for keyless (Entra) access.

## Prerequisites

- Terraform >= 1.9.
- Azure CLI (`az`) logged in: `az login`.
- Environment variable `ARM_SUBSCRIPTION_ID` set to the target subscription
  ID (azurerm 4.x requires it explicitly).
- Owner or User Access Administrator on the target subscription to create
  role assignments.

```powershell
az login
$env:ARM_SUBSCRIPTION_ID = "<your-subscription-id>"
```

## Configure

Copy the example vars file and edit locally:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` is gitignored. `terraform.tfvars.example` is tracked.

## Commands

```powershell
terraform fmt -check -recursive
terraform init -upgrade
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

To tear everything down:

```powershell
terraform destroy
```

## Populate the backend `.env` from outputs

After `terraform apply`, the outputs contain everything the backend needs:

```powershell
$rg   = terraform output -raw resource_group_name
$ep   = terraform output -raw ai_services_endpoint
$proj = terraform output -raw foundry_project_name
$dep  = terraform output -raw model_deployment_name
$ai   = terraform output -raw application_insights_connection_string

Set-Content ../services/api/.env @"
AZURE_AI_FOUNDRY_ENDPOINT=$ep
AZURE_AI_FOUNDRY_PROJECT_NAME=$proj
AZURE_AI_FOUNDRY_DEPLOYMENT=$dep
AZURE_AI_FOUNDRY_API_VERSION=2024-10-21
AZURE_AI_FOUNDRY_AUTH_MODE=entra
APPLICATIONINSIGHTS_CONNECTION_STRING=$ai
DEMO_RESET_ENABLED=false
"@
```

## Expected cost

The prototype uses a Standard AI Services account (S0) and a model
deployment. Actual cost depends on:

- Chosen `model_name`, `model_version`, `model_sku_name`, and `model_capacity`.
- Region.
- Traffic.

Log Analytics + Application Insights add small pay-as-you-go telemetry
costs. Destroy the stack when not in use.

## Model / SKU / region availability

Model availability, SKU support, and TPM quota are region-dependent.
`gpt-4o-mini` on `GlobalStandard` is a broadly available combination but
may require quota. If your region does not support the defaults,
override:

```powershell
terraform apply `
  -var location=westus3 `
  -var model_name=gpt-4o-mini `
  -var model_version=2024-07-18 `
  -var model_sku_name=Standard `
  -var model_capacity=1
```

## RBAC propagation

The role assignments grant your local principal:

- `Cognitive Services OpenAI User` at the AI Services account scope.
- `Azure AI User` at the Foundry project scope.

Role assignments can take several minutes to propagate. First-run
inference may return `401` or `403` briefly.

## Secret handling

- Keyless auth is the only supported path.
- Terraform never reads `primary_access_key` or `secondary_access_key`.
- No Key Vault secret is created for the model key.
- Application Insights connection string is exposed as an output but is
  marked `sensitive = true`; treat it like a secret and never commit it.

## Terraform state

`terraform.tfstate*` may contain resource metadata. Never commit it. This
project uses local state by default; use a remote backend
(Azure Storage + `azurerm` backend) before sharing state with a team.
The `.gitignore` at the repo root already excludes state files.

`.terraform.lock.hcl` is intentionally committed so provider versions are
reproducible.
