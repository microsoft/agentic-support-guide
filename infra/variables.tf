variable "resource_group_name" {
  description = "Base name for the resource group. A random suffix is appended so many learners can deploy into one subscription without colliding."
  type        = string
  default     = "rg-agentic-support-guide"
}

variable "location" {
  description = <<EOT
Azure region for the resource group, AI Services account, Foundry project, and
model deployment. Must be a region that supports Azure AI Foundry and the
selected model / SKU combination. Provide via terraform.tfvars, `-var`, or the
interactive prompt. No default is set so this decision is explicit.
EOT
  type        = string

  validation {
    condition     = length(var.location) > 0
    error_message = "location must be a non-empty Azure region, e.g. eastus2 or swedencentral."
  }
}

variable "ai_services_name" {
  description = "Base name for the Azure AI Services (AIServices) account. A random suffix is appended."
  type        = string
  default     = "ai-foundry-asg"
}

variable "foundry_project_name" {
  description = "Base name for the Azure AI Foundry project. A random suffix is appended, because the project's backing workspace name must stay unique across soft-deleted tombstones."
  type        = string
  default     = "asg-project"
}

variable "foundry_project_display_name" {
  description = "Display name for the Azure AI Foundry project."
  type        = string
  default     = "Agentic Support Guide"
}

variable "model_deployment_name" {
  description = "Name for the model deployment. The API references this via AZURE_AI_FOUNDRY_DEPLOYMENT."
  type        = string
  default     = "asg-chat"
}

variable "model_name" {
  description = <<EOT
Model to deploy. Default `gpt-4.1-mini` is a broadly available cost-efficient
chat model with a support horizon well past the demo window. Check the
current model retirement schedule before customer demos:
https://learn.microsoft.com/azure/ai-services/openai/concepts/model-retirements
EOT
  type        = string
  default     = "gpt-4.1-mini"
}

variable "model_version" {
  description = <<EOT
Model version. Default `2025-04-14` is the GA version of `gpt-4.1-mini`.
Standard and DataZoneStandard SKUs auto-upgrade at base-model retirement,
so this default is safe for demos but should be reviewed for production.
EOT
  type        = string
  default     = "2025-04-14"
}

variable "model_sku_name" {
  description = <<EOT
Deployment SKU. Defaults to `DataZoneStandard`, which keeps inference traffic
inside a single Azure data zone (US or EU) rather than routing globally. Other
valid values include `Standard`, `GlobalStandard`, and `DataZoneBatch`.
Availability is region-dependent.
EOT
  type        = string
  default     = "DataZoneStandard"
}

variable "model_capacity" {
  description = "Deployment capacity, in thousands of tokens per minute. Availability is quota-dependent."
  type        = number
  default     = 10
}

variable "principal_id" {
  description = <<EOT
Entra ID Object ID of the identity that will call the deployed model. The
`Cognitive Services OpenAI User` role is granted at the AI Services
account scope so `az login` + DefaultAzureCredential can reach the model.

Leave empty to default to whoever runs `terraform apply` (that principal's
`object_id` is discovered from `azurerm_client_config.current`). Set this
explicitly to a different Object ID when:

- A different developer will run the demo (they need `az login` as that user).
- A CI or backend service principal will call the model in production.

How to look up an Object ID:

- Your own:  az ad signed-in-user show --query id -o tsv
- Someone else: az ad user show --id someone@example.invalid --query id -o tsv
- Service principal: az ad sp show --id <app-id> --query id -o tsv

This variable takes a single principal today. Extend `rbac.tf` with
additional `azurerm_role_assignment` resources if multiple people need
access.
EOT
  type        = string
  default     = ""
}

variable "additional_principal_ids" {
  description = <<EOT
Extra Entra Object IDs that get the same workshop roles as `principal_id`.

Use this to onboard a room of learners in one apply. An Entra *group* object
ID also works and is the better option above ~10 people, because group
membership changes do not require a re-apply.

  az ad user show --id someone@example.invalid --query id -o tsv
  az ad group show --group "ASG Workshop" --query id -o tsv
EOT
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for id in var.additional_principal_ids :
      length(trimspace(id)) == 0 ||
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", trimspace(id)))
    ])
    error_message = "Each additional_principal_ids entry must be an Entra object ID (GUID), not a UPN or display name."
  }
}

# ---- App hosting (DevOps plane) ---------------------------------------------

variable "enable_app_hosting" {
  description = "Create the App Service plans and the API/web apps."
  type        = bool
  default     = true
}

variable "app_service_sku" {
  description = "App Service Plan SKU. B1 is the cheapest tier with an always-on Linux worker; App Service does not scale to zero, so these bill continuously."
  type        = string
  default     = "B1"
}

variable "api_evidence_source" {
  description = <<EOT
Which evidence retriever the deployed API uses: `fixtures` or `foundry_iq`.

Starts as fixtures so the app runs before Module 3 exists. Module 3 flips it
to foundry_iq once the learner has provisioned a knowledge base.
EOT
  type        = string
  default     = "fixtures"

  validation {
    condition     = contains(["fixtures", "foundry_iq"], var.api_evidence_source)
    error_message = "api_evidence_source must be 'fixtures' or 'foundry_iq'."
  }
}

variable "api_knowledge_base_name" {
  description = "Foundry IQ knowledge base the deployed API queries. Set after Module 3 provisions it."
  type        = string
  default     = ""
}

variable "api_knowledge_source_name" {
  description = <<EOT
Knowledge source the API scopes retrieval to. Leave empty to derive it from
the knowledge base name by swapping the `kb` segment for `ks`, which matches
both `asg-kb-<suffix>` and a portal-created `kb-<suffix>`. Set it explicitly
when the source does not follow that convention.
EOT
  type        = string
  default     = ""
}

variable "log_analytics_retention_days" {
  description = "Log Analytics workspace retention in days."
  type        = number
  default     = 30
}

# ---- Knowledge plane (Foundry IQ, Module 3) --------------------------------

variable "enable_knowledge_plane" {
  description = "Create the Azure AI Search service and blob container that back Foundry IQ. Set false to skip Module 3 infrastructure."
  type        = bool
  default     = true
}

variable "search_name_prefix" {
  description = "Base name fragment for the Search service and storage account. A random suffix is appended."
  type        = string
  default     = "asg"
}

variable "knowledge_storage_public_access" {
  description = <<EOT
Allow public network access to the knowledge storage account.

Learners upload district documents from their own machines in Module 3, which
needs this. Entra auth is still enforced because shared keys are disabled.

Many tenants force this off with Azure Policy. The `SecurityControl = Ignore`
tag in var.tags exempts this workshop environment. If your tenant does not
honour that tag, set this false and expect `terraform plan` to show no drift;
Module 3 then documents the alternative ingestion paths.
EOT
  type        = bool
  default     = true
}

variable "search_location" {
  description = <<EOT
Region for the Azure AI Search service. Leave empty to use var.location.

Search capacity is exhausted per-region independently of Foundry capacity, so
`basic` is often unavailable in the region you picked for Foundry. If apply
fails with `ResourcesForSkuUnavailable` or `InsufficientResourcesAvailable`,
set this to another region. Cross-region only costs retrieval latency.
EOT
  type        = string
  default     = ""
}

variable "search_sku" {
  description = "Azure AI Search SKU. `basic` is the cheapest tier that supports semantic ranking, which agentic retrieval requires. `free` will NOT work."
  type        = string
  default     = "basic"

  validation {
    condition     = contains(["basic", "standard", "standard2", "standard3"], var.search_sku)
    error_message = "search_sku must support semantic ranking: basic, standard, standard2, or standard3."
  }
}

variable "search_replica_count" {
  description = <<EOT
Search replicas. One replica serves roughly three concurrent semantic
requests plus a short queue. A workshop of 30 learners querying at once
will throttle on a single replica; raise this or run learners in waves.
EOT
  type        = number
  default     = 1

  validation {
    condition     = var.search_replica_count >= 1 && var.search_replica_count <= 12
    error_message = "search_replica_count must be between 1 and 12."
  }
}

# ---- Model router (Module 5) ------------------------------------------------

variable "enable_model_router" {
  description = "Deploy the model-router deployment used by Module 5. Availability is region-dependent."
  type        = bool
  default     = true
}

variable "router_deployment_name" {
  description = "Name of the model router deployment."
  type        = string
  default     = "asg-router"
}

variable "router_model_version" {
  description = "Model router version. Each version pins the set of models it can route across."
  type        = string
  default     = "2025-11-18"
}

variable "router_sku_name" {
  description = "SKU for the router deployment. Model router is typically GlobalStandard only."
  type        = string
  default     = "GlobalStandard"
}

variable "router_capacity" {
  description = "Router deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 10
}

# ---- Judge model (Module 8 evaluations) -------------------------------------

variable "enable_judge_deployment" {
  description = "Deploy a separate model used only to grade agent output in Module 8."
  type        = bool
  default     = true
}

variable "judge_deployment_name" {
  description = "Name of the judge model deployment used by evaluations."
  type        = string
  default     = "asg-judge"
}

variable "judge_model_name" {
  description = "Model used to grade agent output. A stronger model than the agents' own model gives more reliable grades."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "judge_model_version" {
  description = "Version of the judge model."
  type        = string
  default     = "2025-04-14"
}

variable "judge_capacity" {
  description = "Judge deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 10
}

# ---- Role grants ------------------------------------------------------------

variable "grant_search_control_plane" {
  description = <<EOT
Grant `Search Service Contributor` so the principal can create and delete
indexes, indexers, and knowledge sources.

This role covers the ENTIRE search service. Azure AI Search has no per-index
RBAC, so index name prefixes are a convention, not an isolation boundary: any
holder can delete any other learner's index. Keep this true only in a
throwaway workshop subscription. Set it false and provision indexes through a
facilitator-owned path for shared or long-lived environments.
EOT
  type        = bool
  default     = true
}

variable "grant_project_ai_user" {
  description = "Grant a project-scope data-plane role, needed to publish prompt agents and run evaluations."
  type        = bool
  default     = true
}

variable "project_role_definition_name" {
  description = <<EOT
Project-scope role granted for publishing prompt agents and running
evaluations. `Azure AI User` is the modern name but is not yet present in
every tenant; `Cognitive Services User` is the portable fallback.
EOT
  type        = string
  default     = "Cognitive Services User"
}



variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default = {
    project = "agentic-support-guide"
    tier    = "prototype"
    # Exempts this throwaway workshop environment from the tenant security
    # policy that otherwise forces storage public network access off, which
    # blocks learners uploading district documents from their machines.
    SecurityControl = "Ignore"
  }
}
