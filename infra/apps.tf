# DevOps plane: the UI and API that Terraform previously did not deploy.
#
# One App Service Plan each, so the API and the UI scale and fail
# independently - a UI redeploy cannot restart the API.

locals {
  api_plan_name = "asp-asg-api-${local.suffix}"
  web_plan_name = "asp-asg-web-${local.suffix}"
  api_app_name  = "app-asg-api-${local.suffix}"
  web_app_name  = "app-asg-web-${local.suffix}"

  api_url = var.enable_app_hosting ? "https://${azurerm_linux_web_app.api[0].default_hostname}" : ""
  web_url = var.enable_app_hosting ? "https://${azurerm_linux_web_app.web[0].default_hostname}" : ""
}

resource "azurerm_service_plan" "api" {
  count = var.enable_app_hosting ? 1 : 0

  name                = local.api_plan_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku

  tags = var.tags
}

resource "azurerm_service_plan" "web" {
  count = var.enable_app_hosting ? 1 : 0

  name                = local.web_plan_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku

  tags = var.tags
}

resource "azurerm_linux_web_app" "api" {
  count = var.enable_app_hosting ? 1 : 0

  name                = local.api_app_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_service_plan.api[0].location
  service_plan_id     = azurerm_service_plan.api[0].id

  https_only = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.13"
    }

    # The deployed zip preserves the repo layout, because
    # app/contracts_registry.py resolves contracts/ via parents[3] and
    # prompt_envelope.py resolves agents/ via parents[4]. --app-dir puts
    # services/api on sys.path without flattening that structure.
    app_command_line = "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir services/api"

    # The provider requires the eviction window whenever a health check path
    # is set; omitting it fails at apply, not at validate.
    health_check_path                 = "/api/health"
    health_check_eviction_time_in_min = 5
    ftps_state                        = "Disabled"
    # Azure already defaults to 1.2. Pinned so a platform default change or a
    # provider upgrade cannot silently weaken it.
    minimum_tls_version = "1.2"

    cors {
      allowed_origins = [local.web_url]
    }
  }

  app_settings = {
    # Oryx installs from the wwwroot-root requirements.txt on deploy.
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    WEBSITES_PORT                  = "8000"

    AZURE_AI_FOUNDRY_PROJECT_ENDPOINT    = "https://${local.custom_subdomain_name}.services.ai.azure.com/api/projects/${azurerm_cognitive_account_project.foundry_project.name}"
    AZURE_AI_FOUNDRY_AUTH_MODE           = "entra"
    FOUNDRY_MODEL_DEPLOYMENT_ANALYST     = var.model_deployment_name
    FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER = var.model_deployment_name
    FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR   = var.model_deployment_name
    FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER   = var.model_deployment_name

    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string

    AZURE_SEARCH_ENDPOINT = var.enable_knowledge_plane ? "https://${azurerm_search_service.knowledge[0].name}.search.windows.net" : ""
    # Module 3 flips this to foundry_iq once a knowledge base exists.
    EVIDENCE_SOURCE           = var.api_evidence_source
    FOUNDRY_IQ_KNOWLEDGE_BASE = var.api_knowledge_base_name
    # Set this when the source name is not <kb name with kb->ks>, which is
    # what the portal walkthrough produces.
    FOUNDRY_IQ_KNOWLEDGE_SOURCE = var.api_knowledge_source_name

    ALLOWED_ORIGINS = local.web_url
  }

  tags = var.tags
}

resource "azurerm_linux_web_app" "web" {
  count = var.enable_app_hosting ? 1 : 0

  name                = local.web_app_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_service_plan.web[0].location
  service_plan_id     = azurerm_service_plan.web[0].id

  https_only = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      node_version = "22-lts"
    }

    # --spa is what makes a refresh on /supports serve index.html instead
    # of returning 404.
    app_command_line = "pm2 serve /home/site/wwwroot --no-daemon --spa"

    ftps_state          = "Disabled"
    minimum_tls_version = "1.2"
  }

  app_settings = {
    # The bundle is prebuilt by the deploy script; Oryx must not rebuild it.
    SCM_DO_BUILD_DURING_DEPLOYMENT = "false"
  }

  tags = var.tags
}
