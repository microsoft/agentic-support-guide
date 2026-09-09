# API authentication.
#
# The API is internet-reachable. Before this, any caller chose their own
# `district_id` in the request body, so district scoping was a suggestion and
# every saved plan and audit row was world-readable.
#
# Easy Auth validates tokens at the platform edge (the `auth_settings_v2`
# block on the API web app in apps.tf), so the app never fetches signing keys
# or handles key rollover. The application still does the part that matters:
# mapping an identity to the districts it may touch.
#
# This registration deliberately declares no redirect URI of its own. Easy
# Auth returns 401 rather than redirecting, because every caller is either a
# SPA holding a bearer token or a script, and a login redirect would be
# unusable for both. Leaving it out also avoids a dependency cycle between the
# API web app and this registration.

locals {
  # A pre-created registration wins, so a tenant where Terraform cannot
  # register applications is still supported.
  byo_api_client_id = trimspace(var.api_client_id)
  create_api_app    = var.enable_app_hosting && var.enable_api_auth && local.byo_api_client_id == ""
  effective_api_client_id = (
    local.byo_api_client_id != "" ? local.byo_api_client_id :
    (local.create_api_app ? azuread_application.api[0].client_id : "")
  )
}

resource "random_uuid" "api_scope" {
  count = local.create_api_app ? 1 : 0
}

resource "azuread_application" "api" {
  count = local.create_api_app ? 1 : 0

  display_name     = local.api_app_name
  sign_in_audience = "AzureADMyOrg"

  api {
    requested_access_token_version = 2

    oauth2_permission_scope {
      id                         = random_uuid.api_scope[0].result
      value                      = "access_as_user"
      type                       = "User"
      admin_consent_display_name = "Access the support guide API"
      admin_consent_description  = "Allows the signed-in user to call the API on their behalf."
      user_consent_display_name  = "Access the support guide API"
      user_consent_description   = "Allows the app to call the API as you."
      enabled                    = true
    }
  }

  # The SPA runs on its own App Service host and signs in with MSAL.
  single_page_application {
    redirect_uris = ["${local.web_url}/"]
  }
}

resource "azuread_service_principal" "api" {
  count = local.create_api_app ? 1 : 0

  client_id = azuread_application.api[0].client_id
}
