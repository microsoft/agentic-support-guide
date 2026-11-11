# Infra - Terraform for agentic-support-guide

Provisions the minimum Microsoft Foundry resources needed for real LLM
calls from the three implemented agents:

- Azure resource group.
- Azure AI Services account (`kind = "AIServices"`, `project_management_enabled = true`).
- Microsoft Foundry project (`azurerm_cognitive_account_project`).
- Three model deployments (`azurerm_cognitive_deployment`): the chat model,
  the Module 9 judge, and the Module 7 router.
- Azure AI Search plus a storage account and a `group-knowledge` container,
  which back Foundry IQ in Module 6 (`enable_knowledge_plane`).
- Two Linux App Service plans and two web apps — one pair for the API, one
  for the UI (`enable_app_hosting`).
- Log Analytics workspace + Application Insights (metadata / telemetry).
- Diagnostic setting routing the AI Services account's own logs and
  metrics into the Log Analytics workspace.
- Eleven RBAC role assignments for keyless (Entra) access.

> **Network exposure.** The AI Services account is created with
> `public_network_access_enabled = true` and no network ACLs. Keyless
> Entra auth (`local_auth_enabled = false`) is the only access control.
> Add a private endpoint or `network_acls` before using this outside a
> prototype.

## Resource naming and collisions

This stack is meant to be deployed many times over — dozens of learners,
frequently into the same subscription. Every name that has to be unique
gets a shared random suffix from `random_string.suffix`:

| Resource | Name | Uniqueness scope |
| --- | --- | --- |
| Resource group | `rg-agentic-support-guide-<suffix>` | Subscription |
| AI Services account | `ai-foundry-asg-<suffix>` | Resource group |
| Custom subdomain | `aifoundryasg<suffix>` | **Global** (DNS) |
| Foundry project | `asg-project-<suffix>` | Account, plus its backing workspace |
| Log Analytics | `log-asg-<suffix>` | Resource group |
| Application Insights | `appi-asg-<suffix>` | Resource group |

Two learners running `terraform apply` in the same subscription get
different suffixes and therefore never collide. Do not hardcode any of
these names.

The suffix also matters on **re-deploy**. Azure soft-deletes both the
Cognitive Services account and the workspace backing the Foundry project,
and a tombstone keeps the old name reserved. A fresh state directory
generates a fresh suffix, so this resolves itself. If you reuse a state
whose resources were deleted out of band, force a new suffix:

```powershell
terraform apply -replace="random_string.suffix"
```

See [Troubleshooting](#troubleshooting-soft-delete) for the errors this
prevents.

## Prerequisites

- Terraform >= 1.9.
- Azure CLI (`az`) logged in: `az login`.
- Owner or User Access Administrator on the target subscription to create
  role assignments.

The azurerm provider infers the subscription from your Azure CLI login, so
`ARM_SUBSCRIPTION_ID` is optional. Set it only to pin a specific subscription
when your `az` context is ambiguous:

```powershell
az login
az account set --subscription "<your-subscription-id>"
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
terraform init                # uses versions from .terraform.lock.hcl
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

### When to use `terraform init -upgrade`

Plain `terraform init` respects the committed `.terraform.lock.hcl` and
gives you the exact provider versions the maintainers tested against. Use
that for demos and CI.

Use `terraform init -upgrade` only when you deliberately want newer
providers within the version constraints in `providers.tf` (currently
`azurerm >= 4.40.0, < 5.0.0` and `random ~> 3.6`). It re-resolves and
rewrites the lock file. After running it, re-run `terraform validate` and
`terraform plan` before committing the new lock, because a newer provider
can change plan output or fail against `azurerm_cognitive_account_project`
in edge cases.

To tear everything down:

```powershell
terraform destroy
```

## Populate the backend `.env` from outputs

After `terraform apply`, the fastest path is the helper script from the
repo root:

```powershell
cd ..
.\scripts\populate-env.ps1
```

The script reads all Terraform outputs (including the sensitive
Application Insights connection string), writes `services/api/.env`,
overwrites any prior file, and never prints the sensitive value to the
console. Re-run it after any future `terraform apply` that changes
outputs.

### Manual alternative

If you'd rather do it by hand:

1. Copy `services/api/.env.example` to `services/api/.env`.
2. From `infra/`, run `terraform output`.
3. Open `services/api/.env` in VS Code and paste the values into the
   corresponding `AZURE_AI_FOUNDRY_*` keys:

   - `foundry_project_endpoint` → `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
   - `model_deployment_name`    → `FOUNDRY_MODEL_DEPLOYMENT_ANALYST`,
     `FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER`,
     `FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR` and
     `FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER`
   - `application_insights_connection_string` (sensitive; see it with
     `terraform output -raw application_insights_connection_string`) →
     `APPLICATIONINSIGHTS_CONNECTION_STRING`

4. Save. `.env` is gitignored; `.env.example` is tracked and contains
   only placeholders.

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
answer the interactive prompt. Common choices: `westus3`, `eastus2`,
`swedencentral`.

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

`rbac.tf` creates **eleven** role assignments: five to whoever runs `apply`
(`Cognitive Services OpenAI User` at the account scope, the project role at
the project scope, `Search Service Contributor`, `Search Index Data
Contributor`, and `Storage Blob Data Contributor`) and six to service
identities (the search service, the AI Services account and the API web app).

Both the account-scope and the project-scope grants are required. Account
scope authorizes plain model calls; the app reaches its agents through the
project endpoint, which is a separate scope. Missing the project grant gives
`AGENT_PROVIDER_AUTH_DENIED` on the first agent call while health still
reports ok.

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

## Troubleshooting (soft delete)
<a id="troubleshooting-soft-delete"></a>

Both errors below mean a previous deployment reserved the name and Azure is
holding a soft-delete tombstone.

**`FlagMustBeSetForRestore: An existing resource ... has been soft-deleted`**
— the Cognitive Services account name is tombstoned.

**`ResourceProviderExtensionError ... Soft-deleted workspace exists`**
— the workspace behind the Foundry project is tombstoned. Purging the
Cognitive Services account does *not* clear this one.

Preferred fix — take a new suffix so nothing collides:

```powershell
terraform apply -replace="random_string.suffix"
```

Alternative — purge the tombstone and keep the current name:

```powershell
az cognitiveservices account list-deleted --query "[].{name:name,location:location}" -o table
az cognitiveservices account purge -l <location> -g <resource-group> -n <account-name>
```

Purging is permanent. Only purge accounts belonging to this stack; the
listing is subscription-wide and may include other people's resources.

**`a resource with the ID ... already exists - to be managed via Terraform
this resource needs to be imported`** — a previous apply created the
resource but failed before recording it in state. Either
`terraform import` it, or delete it in Azure and re-apply.
