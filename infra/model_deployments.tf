# Extra model deployments for the workshop modules.
#
# Cognitive Services serializes control-plane operations per account, so
# every deployment chains off the previous one. Parallel creates return
# 409 RequestConflict.

# Module 5: one deployment that routes across several underlying models.
# NOTE: the router's effective context window is capped by the SMALLEST
# model behind it, not the largest.
resource "azurerm_cognitive_deployment" "router" {
  count = var.enable_model_router ? 1 : 0

  name                 = var.router_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id

  depends_on = [azurerm_cognitive_deployment.chat]

  model {
    format  = "OpenAI"
    name    = "model-router"
    version = var.router_model_version
  }

  sku {
    name     = var.router_sku_name
    capacity = var.router_capacity
  }
}

# Module 8: the judge model that grades agent output. Kept separate from
# the agents' own deployment so grading load never starves the agents and
# so learners can see the judge is a different model.
resource "azurerm_cognitive_deployment" "judge" {
  count = var.enable_judge_deployment ? 1 : 0

  name                 = var.judge_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id

  # Chat is listed explicitly: when the router is disabled its count is 0,
  # leaving no ordering edge and letting this deploy in parallel with chat,
  # which the account rejects with 409 RequestConflict.
  depends_on = [
    azurerm_cognitive_deployment.chat,
    azurerm_cognitive_deployment.router,
  ]

  model {
    format  = "OpenAI"
    name    = var.judge_model_name
    version = var.judge_model_version
  }

  sku {
    name     = var.model_sku_name
    capacity = var.judge_capacity
  }
}
