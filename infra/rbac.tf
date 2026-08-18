# Cognitive Services OpenAI User at the AI Services account scope.
# Enables keyless (Entra) chat completion calls from developer workstations.
resource "azurerm_role_assignment" "cognitive_openai_user" {
  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = local.effective_principal_id
}

# Azure AI User at the Foundry project scope for project-scoped SDK calls.
resource "azurerm_role_assignment" "ai_user_project" {
  scope                = azurerm_cognitive_account_project.foundry_project.id
  role_definition_name = "Azure AI User"
  principal_id         = local.effective_principal_id
}
