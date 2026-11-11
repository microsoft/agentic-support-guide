# Cognitive Services OpenAI User at the AI Services account scope.
# Grants keyless (Entra) chat completion calls from developer workstations.
# The backend calls the account endpoint, so this account-scope role is what
# actually authorizes runtime inference.
#
# All workshop roles use for_each over local.workshop_principal_ids. That is
# normally just the person running apply - each learner deploys their own
# stack - plus anyone listed in additional_principal_ids.
resource "azurerm_role_assignment" "cognitive_openai_user" {
  for_each = local.workshop_principal_ids

  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}

# Publishing prompt agents and running evaluations are project-scope
# operations, not account-scope inference.
resource "azurerm_role_assignment" "project_user" {
  for_each = var.grant_project_ai_user ? local.workshop_principal_ids : toset([])

  scope                = azurerm_cognitive_account_project.foundry_project.id
  role_definition_name = var.project_role_definition_name
  principal_id         = each.value
}

# ---- Knowledge plane (Foundry IQ) ------------------------------------------
#
# SECURITY NOTE, read before reusing this outside the workshop:
# `Search Service Contributor` is scoped to the WHOLE search service. Azure AI
# Search has no per-index RBAC. Index name prefixes are a naming convention,
# not an authorization boundary: any holder of this role can list, read, and
# DELETE every index on the service.
# Harmless here, where the service has exactly one owner. Not harmless where
# several teams or customers share one search service - there, set
# grant_search_control_plane = false and pre-create indexes out of band.

resource "azurerm_role_assignment" "search_service_contributor" {
  for_each = (
    var.enable_knowledge_plane && var.grant_search_control_plane
    ? local.workshop_principal_ids
    : toset([])
  )

  scope                = azurerm_search_service.knowledge[0].id
  role_definition_name = "Search Service Contributor"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "search_index_data_contributor" {
  for_each = var.enable_knowledge_plane ? local.workshop_principal_ids : toset([])

  scope                = azurerm_search_service.knowledge[0].id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "storage_blob_data_contributor" {
  for_each = var.enable_knowledge_plane ? local.workshop_principal_ids : toset([])

  scope                = azurerm_storage_account.knowledge[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}

# The Search service reads source documents from blob using its own managed
# identity, so the indexer never needs a storage key.
resource "azurerm_role_assignment" "search_reads_blob" {
  count = var.enable_knowledge_plane ? 1 : 0

  scope                = azurerm_storage_account.knowledge[0].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_search_service.knowledge[0].identity[0].principal_id
}

# The AI Services account queries the Search index on the agent's behalf
# during agentic retrieval.
resource "azurerm_role_assignment" "ai_services_reads_index" {
  count = var.enable_knowledge_plane ? 1 : 0

  scope                = azurerm_search_service.knowledge[0].id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azurerm_cognitive_account.ai_services.identity[0].principal_id
}

# ---- Deployed app identities ------------------------------------------------
#
# The API runs as itself in Azure, not as the learner who deployed it, so it
# needs its own grants. Without these the deployed app returns 403 on the
# first model call - a failure that only shows up after deployment.

resource "azurerm_role_assignment" "api_calls_models" {
  count = var.enable_app_hosting ? 1 : 0

  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_web_app.api[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "api_reads_index" {
  count = var.enable_app_hosting && var.enable_knowledge_plane ? 1 : 0

  scope                = azurerm_search_service.knowledge[0].id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azurerm_linux_web_app.api[0].identity[0].principal_id
}

# Account-scope inference is not enough. The app reaches its agents through the
# project endpoint, which is a separate RBAC scope; without this the deployed
# app returns AGENT_PROVIDER_AUTH_DENIED on the first agent call even though
# plain model calls succeed.
resource "azurerm_role_assignment" "api_uses_project" {
  count = var.enable_app_hosting ? 1 : 0

  scope                = azurerm_cognitive_account_project.foundry_project.id
  role_definition_name = var.project_role_definition_name
  principal_id         = azurerm_linux_web_app.api[0].identity[0].principal_id
}

# Foundry IQ knowledge bases that include a web source reason with a model,
# so the search service itself must be able to call it.
resource "azurerm_role_assignment" "search_calls_models" {
  count = var.enable_knowledge_plane ? 1 : 0

  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_search_service.knowledge[0].identity[0].principal_id
}
