resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-asg-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_analytics_retention_days
  tags                = var.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-asg-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = var.tags
}

# Without this the workspace above receives application telemetry only. The
# account's own audit / request / trace logs are what show who invoked which
# agent, so route them to the same workspace.
data "azurerm_monitor_diagnostic_categories" "ai_services" {
  resource_id = azurerm_cognitive_account.ai_services.id
}

resource "azurerm_monitor_diagnostic_setting" "ai_services" {
  name                       = "diag-ai-services"
  target_resource_id         = azurerm_cognitive_account.ai_services.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  dynamic "enabled_log" {
    for_each = data.azurerm_monitor_diagnostic_categories.ai_services.log_category_types
    content {
      category = enabled_log.value
    }
  }

  dynamic "enabled_metric" {
    for_each = data.azurerm_monitor_diagnostic_categories.ai_services.metrics
    content {
      category = enabled_metric.value
    }
  }
}
