# Shared key between the web tier and the API.
#
# The web tier attaches it server-side on every forwarded request, so the
# browser never receives it. This authenticates the web tier to the API; it is
# not a user credential and there is no user sign-in anywhere in this stack.
#
# Generated rather than configured: a key nobody chooses is a key nobody
# reuses, commits, or types into a chat window. It lives in Terraform state,
# which is local and gitignored here - treat that file as sensitive.
#
# To rotate: `terraform apply -replace=random_password.api_shared_key`. Both
# app settings update in the same apply, so there is a brief window where the
# two tiers disagree and the API returns 401.

resource "random_password" "api_shared_key" {
  length = 48
  # App settings and shell exports travel through enough layers that a
  # punctuation-free key avoids a whole class of quoting bugs.
  special = false
}

locals {
  api_shared_key = random_password.api_shared_key.result
}
