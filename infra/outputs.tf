output "resource_group_name" {
  description = "Resource group holding the prototype infrastructure."
  value       = azurerm_resource_group.main.name
}

output "ai_services_account_name" {
  description = "Azure AI Services (AIServices kind) account name."
  value       = azurerm_cognitive_account.ai_services.name
}

output "ai_services_endpoint" {
  description = "AI Services endpoint used by the AzureFoundryLlmProvider for chat completions."
  value       = azurerm_cognitive_account.ai_services.endpoint
}

output "foundry_project_name" {
  description = "Azure AI Foundry project name."
  value       = azurerm_cognitive_account_project.foundry_project.name
}

output "foundry_project_id" {
  description = "Azure AI Foundry project resource ID."
  value       = azurerm_cognitive_account_project.foundry_project.id
}

output "foundry_project_endpoints" {
  description = "Endpoint map exported by the Foundry project. Used for observability and future project-scoped SDK routing."
  value       = azurerm_cognitive_account_project.foundry_project.endpoints
}

output "model_deployment_name" {
  description = "Deployment name to set as AZURE_AI_FOUNDRY_DEPLOYMENT in the backend .env."
  value       = azurerm_cognitive_deployment.chat.name
}

output "log_analytics_workspace_name" {
  description = "Log Analytics workspace name (metadata only)."
  value       = azurerm_log_analytics_workspace.main.name
}

output "application_insights_name" {
  description = "Application Insights resource name (metadata only)."
  value       = azurerm_application_insights.main.name
}

output "application_insights_connection_string" {
  description = "Application Insights connection string. Set as APPLICATIONINSIGHTS_CONNECTION_STRING in the backend .env."
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}
