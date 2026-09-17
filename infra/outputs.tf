output "resource_group_name" {
  description = "Resource group holding the prototype infrastructure."
  value       = azurerm_resource_group.main.name
}

output "ai_services_account_name" {
  description = "Azure AI Services (AIServices kind) account name."
  value       = azurerm_cognitive_account.ai_services.name
}

# Module 5 needs this as the --scope for its role assignment. Without it the
# learner has to hand-assemble the ARM resource ID.
output "ai_services_account_id" {
  description = "Azure AI Services account resource ID, used as an RBAC scope."
  value       = azurerm_cognitive_account.ai_services.id
}

output "ai_services_endpoint" {
  description = "AI Services account endpoint (base). Not used directly by the backend."
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

output "foundry_project_endpoint" {
  description = "Azure AI Foundry project endpoint used by AgentsClient. Set as AZURE_AI_FOUNDRY_PROJECT_ENDPOINT in the backend .env."
  value       = "https://${local.custom_subdomain_name}.services.ai.azure.com/api/projects/${azurerm_cognitive_account_project.foundry_project.name}"
}

output "foundry_project_endpoints" {
  description = "Endpoint map exported by the Foundry project. Debug output; do not consume in scripts."
  value       = azurerm_cognitive_account_project.foundry_project.endpoints
}

output "model_deployment_name" {
  description = "Shared model deployment name. Use for FOUNDRY_MODEL_DEPLOYMENT_ANALYST/RECOMMENDER/VALIDATOR unless you split deployments."
  value       = azurerm_cognitive_deployment.chat.name
}

output "log_analytics_workspace_name" {
  description = "Log Analytics workspace name (metadata only)."
  value       = azurerm_log_analytics_workspace.main.name
}

output "api_url" {
  description = "Deployed API base URL. Empty when app hosting is disabled."
  value       = local.api_url
}

output "web_url" {
  description = "Deployed UI URL. Empty when app hosting is disabled."
  value       = local.web_url
}

output "api_app_name" {
  description = "App Service name for the API, used by scripts/deploy-app.ps1."
  value       = var.enable_app_hosting ? azurerm_linux_web_app.api[0].name : ""
}

output "web_app_name" {
  description = "App Service name for the UI, used by scripts/deploy-app.ps1."
  value       = var.enable_app_hosting ? azurerm_linux_web_app.web[0].name : ""
}

output "router_deployment_name" {
  description = "Model router deployment name. Set as FOUNDRY_MODEL_DEPLOYMENT_ROUTER for Module 7. Empty when the router is disabled."
  value       = var.enable_model_router ? azurerm_cognitive_deployment.router[0].name : ""
}

output "judge_deployment_name" {
  description = "Judge model deployment used by Module 9 evaluations. Set as FOUNDRY_MODEL_DEPLOYMENT_JUDGE. Empty when disabled."
  value       = var.enable_judge_deployment ? azurerm_cognitive_deployment.judge[0].name : ""
}

output "search_service_name" {
  description = "Azure AI Search service backing Foundry IQ. Empty when the knowledge plane is disabled."
  value       = var.enable_knowledge_plane ? azurerm_search_service.knowledge[0].name : ""
}

output "search_endpoint" {
  description = "Search endpoint. Set as AZURE_SEARCH_ENDPOINT for Module 6."
  value       = var.enable_knowledge_plane ? "https://${azurerm_search_service.knowledge[0].name}.search.windows.net" : ""
}

output "knowledge_storage_account_name" {
  description = "Storage account holding dealer group source documents for Foundry IQ."
  value       = var.enable_knowledge_plane ? azurerm_storage_account.knowledge[0].name : ""
}

output "knowledge_storage_account_id" {
  description = "Resource id of the knowledge storage account. Foundry IQ blob sources authenticate with a managed identity using this, not a key."
  value       = var.enable_knowledge_plane ? azurerm_storage_account.knowledge[0].id : ""
}

output "knowledge_container_name" {
  description = "Blob container holding dealer group source documents."
  value       = var.enable_knowledge_plane ? azurerm_storage_container.knowledge[0].name : ""
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

output "api_shared_key" {
  description = "Key the web tier sends to the API. Scripts need it to call the API directly."
  value       = local.api_shared_key
  sensitive   = true
}
