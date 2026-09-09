# Knowledge plane for Foundry IQ (Module 3).
#
# Foundry IQ builds a knowledge base over an Azure AI Search index. The
# blob container holds the district source documents that get indexed.
# Both carry the random suffix so a whole workshop can deploy into one
# subscription.

locals {
  search_service_name = "srch-${var.search_name_prefix}-${local.suffix}"
  # Search capacity runs out per-region independently of Foundry capacity, so
  # this can differ from var.location. Cross-region adds retrieval latency.
  search_location = length(var.search_location) > 0 ? var.search_location : var.location
  # Storage account names: 3-24 chars, lowercase alphanumeric only.
  storage_account_name = substr(replace(lower("st${var.search_name_prefix}${local.suffix}"), "-", ""), 0, 24)
}

resource "azurerm_search_service" "knowledge" {
  count = var.enable_knowledge_plane ? 1 : 0

  name                = local.search_service_name
  resource_group_name = azurerm_resource_group.main.name
  location            = local.search_location
  sku                 = var.search_sku
  # Semantic ranker is what agentic retrieval scores with.
  semantic_search_sku = "standard"

  # One replica serves roughly three concurrent semantic requests. Raise
  # search_replica_count for a live workshop or learners will see throttling.
  replica_count   = var.search_replica_count
  partition_count = 1

  local_authentication_enabled = false

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_storage_account" "knowledge" {
  count = var.enable_knowledge_plane ? 1 : 0

  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false

  # Declared explicitly, not left to the provider default. Many tenants
  # enforce "disabled" with Azure Policy; leaving this implicit makes every
  # plan show perpetual drift as Terraform tries to turn it back on.
  public_network_access_enabled = var.knowledge_storage_public_access

  tags = var.tags
}

resource "azurerm_storage_container" "knowledge" {
  count = var.enable_knowledge_plane ? 1 : 0

  name                  = "district-knowledge"
  storage_account_id    = azurerm_storage_account.knowledge[0].id
  container_access_type = "private"
}
