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

variable "log_analytics_retention_days" {
  description = "Log Analytics workspace retention in days."
  type        = number
  default     = 30
}

# ---- Knowledge plane (Foundry IQ, Module 2) --------------------------------

variable "enable_knowledge_plane" {
  description = "Create the Azure AI Search service and blob container that back Foundry IQ. Set false to skip Module 2 infrastructure."
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

Defaults to false because many enterprise tenants enforce this with Azure
Policy. When it is false you cannot upload blobs from a laptop - the Search
indexer still can, because the account allows trusted Azure services.

Leave false unless you have confirmed your subscription permits public
access; otherwise Terraform will fight the policy on every plan. Module 2A
explains how to ingest documents either way.
EOT
  type        = bool
  default     = false
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

# ---- Model router (Module 3) ------------------------------------------------

variable "enable_model_router" {
  description = "Deploy the model-router deployment used by Module 3. Availability is region-dependent."
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

# ---- Judge model (Module 6 evaluations) -------------------------------------

variable "enable_judge_deployment" {
  description = "Deploy a separate model used only to grade agent output in Module 6."
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
  }
}
