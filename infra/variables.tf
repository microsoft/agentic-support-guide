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
  description = "Model name to deploy (e.g. gpt-4o-mini). Availability is region-dependent."
  type        = string
  default     = "gpt-4o-mini"
}

variable "model_version" {
  description = "Model version. Availability is region-dependent."
  type        = string
  default     = "2024-07-18"
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
  description = "Principal ID that receives RBAC to call the deployed model. Defaults to the current caller."
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
