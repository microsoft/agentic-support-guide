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

1. Copy `terraform.tfvars.example` to `terraform.tfvars` in the same folder.
   In VS Code, right-click the file in the Explorer and choose **Copy**,
   then paste and rename to `terraform.tfvars`. From a terminal:

   ```powershell
   Copy-Item terraform.tfvars.example terraform.tfvars
   ```

2. Open `terraform.tfvars` in VS Code and edit the values. The file is
   commented top-to-bottom; the only required value is `location`.

`terraform.tfvars` is gitignored. `terraform.tfvars.example` is tracked.

If you skip this step, `terraform plan` and `terraform apply` will
interactively prompt for `location` because it has no default.

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

After `terraform apply`, print the values you need:

```powershell
terraform output
```

Then, in VS Code:

1. Open `services/api/.env.example`, right-click and **Copy**, then paste
   as `services/api/.env` in the same folder. (Or from a terminal:
   `Copy-Item ../services/api/.env.example ../services/api/.env`.)
2. Open the new `services/api/.env` in VS Code and paste in the values
   from `terraform output`:

   - `ai_services_endpoint`     → `AZURE_AI_FOUNDRY_ENDPOINT`
   - `foundry_project_name`     → `AZURE_AI_FOUNDRY_PROJECT_NAME`
   - `model_deployment_name`    → `AZURE_AI_FOUNDRY_DEPLOYMENT`
   - `application_insights_connection_string` (sensitive output; run
     `terraform output -raw application_insights_connection_string` to
     see it) → `APPLICATIONINSIGHTS_CONNECTION_STRING`

3. Save. `.env` is gitignored; the `.env.example` file is tracked and
   contains only placeholders.

## Expected cost

The prototype uses a Standard AI Services account (S0) and a model
deployment. Actual cost depends on:

- Chosen `model_name`, `model_version`, `model_sku_name`, and `model_capacity`.
- Region.
- Traffic.

Log Analytics + Application Insights add small pay-as-you-go telemetry
costs. Destroy the stack when not in use.

## Model / SKU / region availability

Region choice is explicit — the `location` variable has no default, so
you must supply it via `terraform.tfvars`, `-var location=<region>`, or
answer the interactive prompt. Common choices: `eastus2`,
`swedencentral`, `westus3`.

The default `model_sku_name` is `DataZoneStandard`, which keeps inference
traffic inside a single Azure data zone (US or EU). Other valid values:

- `Standard` — regional single-region deployment.
- `GlobalStandard` — traffic can route globally.
- `DataZoneBatch` — batch equivalent of `DataZoneStandard`.

Model availability, SKU support, and TPM quota are region-dependent.
The default `gpt-4.1-mini` (`2025-04-14`) on `DataZoneStandard` is a
broadly available cost-efficient combination with a support horizon well
past a demo window. Standard and DataZoneStandard SKUs auto-upgrade at
base-model retirement. See the current
[model retirement schedule](https://learn.microsoft.com/azure/ai-services/openai/concepts/model-retirements)
before customer demos.

If your region does not support the defaults, override in
`terraform.tfvars`:

```hcl
location       = "westus3"
model_name     = "gpt-4.1-mini"
model_version  = "2025-04-14"
model_sku_name = "Standard"
model_capacity = 1
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
