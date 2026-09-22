locals {
  suffix                = random_string.suffix.result
  ai_services_name      = "${var.ai_services_name}-${local.suffix}"
  custom_subdomain_name = replace("${var.ai_services_name}${local.suffix}", "-", "")
  tags                  = merge(var.tags, var.additional_tags)
  # Dozens of learners deploy this into shared subscriptions, so every
  # uniqueness-scoped name carries the suffix. The project also provisions a
  # backing AML workspace that soft-deletes on destroy; without the suffix a
  # re-apply fails with "Soft-deleted workspace exists".
  resource_group_name    = "${var.resource_group_name}-${local.suffix}"
  foundry_project_name   = "${var.foundry_project_name}-${local.suffix}"
  effective_principal_id = length(trimspace(var.principal_id)) > 0 ? trimspace(var.principal_id) : data.azurerm_client_config.current.object_id

  # Everyone who needs workshop roles. Blank entries are dropped and the set
  # deduplicates, so re-listing the deployer does not fail the apply.
  workshop_principal_ids = toset(concat(
    [local.effective_principal_id],
    [for id in var.additional_principal_ids : trimspace(id) if length(trimspace(id)) > 0],
  ))
}

resource "azurerm_resource_group" "main" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_cognitive_account" "ai_services" {
  name                = local.ai_services_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  kind                          = "AIServices"
  sku_name                      = "S0"
  project_management_enabled    = true
  custom_subdomain_name         = local.custom_subdomain_name
  local_auth_enabled            = false
  public_network_access_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_cognitive_account_project" "foundry_project" {
  name                 = local.foundry_project_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id
  location             = azurerm_resource_group.main.location
  display_name         = var.foundry_project_display_name
  description          = "Microsoft Foundry project hosting the three-agent workflow model deployment."

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id

  # Cognitive Services serializes control-plane ops per account. Forcing the
  # deployment after the project prevents 409 RequestConflict on parallel apply.
  depends_on = [azurerm_cognitive_account_project.foundry_project]

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = var.model_sku_name
    capacity = var.model_capacity
  }
}
