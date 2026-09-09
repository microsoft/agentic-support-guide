# DevOps plane: the UI and API that Terraform previously did not deploy.
#
# One App Service Plan each, so the API and the UI scale and fail
# independently - a UI redeploy cannot restart the API.

locals {
  api_plan_name = "asp-asg-api-${local.suffix}"
  web_plan_name = "asp-asg-web-${local.suffix}"
  api_app_name  = "app-asg-api-${local.suffix}"

  # Default the facilitator to whoever ran apply, so the person who created
  # the environment can actually use it without a second config step.
  effective_facilitators = length(var.facilitator_object_ids) > 0 ? var.facilitator_object_ids : [data.azurerm_client_config.current.object_id]
  web_app_name           = "app-asg-web-${local.suffix}"

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

    # Never "disabled" for a deployed app. /api/health/details reports this so
    # an unauthenticated deployment is visible from outside.
    API_AUTH_MODE          = var.enable_api_auth ? "entra" : "disabled"
    FACILITATOR_OBJECT_IDS = join(",", local.effective_facilitators)
    DISTRICT_ASSIGNMENTS = join(
      ",",
      [for oid, districts in var.district_assignments : "${oid}=${join("|", districts)}"]
    )

    ALLOWED_ORIGINS = local.web_url
  }

  # Easy Auth validates the token at the platform edge; the app authorizes.
  # `Return401` rather than a login redirect: every caller is a SPA holding a
  # bearer token or a script, and both would break on a 302 to a login page.
  dynamic "auth_settings_v2" {
    for_each = var.enable_api_auth ? [1] : []
    content {
      auth_enabled           = true
      require_authentication = true
      unauthenticated_action = "Return401"
      require_https          = true
      # Health stays reachable: deploy-app.ps1 polls it to detect a stale
      # build, and that runs before anyone has signed in.
      excluded_paths = ["/api/health", "/api/health/details"]

      active_directory_v2 {
        client_id            = local.effective_api_client_id
        tenant_auth_endpoint = "https://login.microsoftonline.com/${data.azurerm_client_config.current.tenant_id}/v2.0"
        # Both forms: v2.0 access tokens carry the bare app-ID GUID as `aud`,
        # while the identifier URI is what callers request a scope against.
        # Listing only the URI makes Easy Auth reject every valid token with a
        # bodiless 403.
        allowed_audiences = [
          local.effective_api_client_id,
          "api://${local.effective_api_client_id}",
        ]
        # No client secret: the SPA signs in with PKCE and Easy Auth only
        # validates the presented token here.
        client_secret_setting_name = "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"
      }

      login {
        token_store_enabled = false
      }
    }
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
