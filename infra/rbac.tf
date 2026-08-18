# Cognitive Services OpenAI User at the AI Services account scope.
# Grants keyless (Entra) chat completion calls from developer workstations.
# The backend calls the account endpoint, so this account-scope role is what
# actually authorizes runtime inference.
resource "azurerm_role_assignment" "cognitive_openai_user" {
  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = local.effective_principal_id
}

# NOTE: a project-scope role assignment (e.g. "Azure AI User" or
# "Cognitive Services User") would only be needed if the backend later
# switches to the Foundry project endpoint. "Azure AI User" is not
# universally available in every tenant yet; add "Cognitive Services User"
# on `azurerm_cognitive_account_project.foundry_project.id` if you migrate
# to project-scoped SDK routing.
