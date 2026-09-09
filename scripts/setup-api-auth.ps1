# Creates the Entra app registration the API uses for Easy Auth.
#
# Terraform can also create this (infra/auth.tf), but two things make a script
# the more reliable path:
#
#   1. Continuous Access Evaluation can reject the azuread provider's token
#      with `TokenCreatedWithOutdatedPolicies` even when `az` itself works.
#   2. Registering an application needs tenant permission that a workshop
#      learner may not have, so this has to be a step someone else can run.
#
# Feed the resulting client id back with:
#   api_client_id = "<client id>"   in infra/terraform.tfvars

[CmdletBinding()]
param(
    [string]$DisplayName = "",
    [string]$WebUrl = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$infra = Join-Path $repoRoot "infra"

function Get-Output([string]$name) {
    Push-Location $infra
    try { return (terraform output -raw $name 2>$null) } finally { Pop-Location }
}

if (-not $DisplayName) { $DisplayName = Get-Output "api_app_name" }
if (-not $WebUrl) { $WebUrl = Get-Output "web_url" }

if (-not $DisplayName) {
    Write-Host "Could not determine the API app name. Run terraform apply first, or pass -DisplayName." -ForegroundColor Red
    exit 1
}

Write-Host "App registration : $DisplayName" -ForegroundColor Cyan
Write-Host "SPA redirect     : $WebUrl/" -ForegroundColor Cyan

$existing = az ad app list --display-name $DisplayName --query "[0].appId" -o tsv 2>$null
if ($existing) {
    Write-Host "Reusing existing registration $existing" -ForegroundColor Yellow
    $appId = $existing
} else {
    $appId = az ad app create --display-name $DisplayName --sign-in-audience AzureADMyOrg --query appId -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $appId) {
        Write-Host "Could not create the app registration." -ForegroundColor Red
        Write-Host "You need permission to register applications in the tenant." -ForegroundColor Yellow
        Write-Host "Ask an administrator, or set enable_api_auth = false to run without auth" -ForegroundColor Yellow
        Write-Host "(the API is then open to anyone who can reach it)." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Created $appId" -ForegroundColor Green
}

# Expose a delegated scope so the SPA can request a token for this API.
$scopeId = [guid]::NewGuid().ToString()
$objectId = az ad app show --id $appId --query id -o tsv

$apiBody = @{
    api = @{
        requestedAccessTokenVersion = 2
        oauth2PermissionScopes      = @(
            @{
                id                      = $scopeId
                value                   = "access_as_user"
                type                    = "User"
                isEnabled               = $true
                adminConsentDisplayName = "Access the support guide API"
                adminConsentDescription = "Allows the signed-in user to call the API on their behalf."
                userConsentDisplayName  = "Access the support guide API"
                userConsentDescription  = "Allows the app to call the API as you."
            }
        )
    }
    identifierUris  = @("api://$appId")
    spa             = @{ redirectUris = @("$WebUrl/") }
} | ConvertTo-Json -Depth 6 -Compress

$tmp = New-TemporaryFile
Set-Content -Path $tmp -Value $apiBody -Encoding utf8
az rest --method PATCH --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
    --headers "Content-Type=application/json" --body "@$tmp" -o none
$patched = $LASTEXITCODE
Remove-Item $tmp -Force
if ($patched -ne 0) {
    Write-Host "Registration created but the scope could not be configured." -ForegroundColor Yellow
}

# The service principal is what token issuance and consent bind to.
$spExists = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv 2>$null
if (-not $spExists) {
    az ad sp create --id $appId -o none
}

# Pre-authorize the Azure CLI. Without this, every script and CI job that
# calls `az account get-access-token --resource api://<id>` fails with
# AADSTS65001 ("has not consented"), because the CLI is a separate client
# application asking for a scope on ours.
$azureCliClientId = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
$scopeIdLive = az ad app show --id $appId --query "api.oauth2PermissionScopes[0].id" -o tsv 2>$null
if ($scopeIdLive) {
    $preAuth = @{
        api = @{
            preAuthorizedApplications = @(
                @{ appId = $azureCliClientId; delegatedPermissionIds = @($scopeIdLive) }
            )
        }
    } | ConvertTo-Json -Depth 6 -Compress

    $tmp2 = New-TemporaryFile
    Set-Content -Path $tmp2 -Value $preAuth -Encoding utf8
    az rest --method PATCH --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
        --headers "Content-Type=application/json" --body "@$tmp2" -o none
    $preAuthResult = $LASTEXITCODE
    Remove-Item $tmp2 -Force
    if ($preAuthResult -eq 0) {
        Write-Host "Azure CLI pre-authorized (scripts can acquire tokens)." -ForegroundColor Green
    } else {
        Write-Host "Could not pre-authorize the Azure CLI; scripts will hit AADSTS65001." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Add this to infra/terraform.tfvars, then re-run terraform apply:" -ForegroundColor Green
Write-Host ""
Write-Host "  api_client_id = `"$appId`""
Write-Host ""
Write-Host "Scope for clients: api://$appId/access_as_user"
Write-Host ""
Write-Host "Easy Auth changes do not take effect until the worker recycles:" -ForegroundColor Yellow
Write-Host "  az webapp restart -g <resource-group> -n <api app name>"
