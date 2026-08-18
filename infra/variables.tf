variable "resource_group_name" {
  description = "Resource group for the prototype."
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
  description = "Azure AI Foundry project name under the AI Services account."
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
Entra ID Object ID of the identity that will call the deployed model. Two
role assignments (`Cognitive Services OpenAI User` on the AI Services
account, `Azure AI User` on the Foundry project) are granted to this
principal so `az login` + DefaultAzureCredential can reach the model.

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

variable "log_analytics_retention_days" {
  description = "Log Analytics workspace retention in days."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default = {
    project = "agentic-support-guide"
    tier    = "prototype"
  }
}
