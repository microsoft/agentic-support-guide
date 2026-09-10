# Build and deploy the API and UI to App Service.
#
# Module 1. This is the DevOps half of the workshop: the same build and
# release loop CI would run, done by hand once so it is not a black box.
#
#   .\scripts\deploy-app.ps1              # both
#   .\scripts\deploy-app.ps1 -Only api    # just the API
#
# The API zip deliberately preserves the repo layout. app/contracts_registry.py
# resolves contracts/ via parents[3] and prompt_envelope.py resolves agents/
# via parents[4]; flattening services/api to the zip root breaks both at
# import time.

[CmdletBinding()]
param(
    [ValidateSet("both", "api", "web")]
    [string]$Only = "both"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$infra = Join-Path $repoRoot "infra"

function Get-Output([string]$name) {
    Push-Location $infra
    try { return (terraform output -raw $name 2>$null) } finally { Pop-Location }
}

$apiApp = Get-Output "api_app_name"
$webApp = Get-Output "web_app_name"
$resourceGroup = Get-Output "resource_group_name"
$apiUrl = Get-Output "api_url"
$webUrl = Get-Output "web_url"

if (-not $apiApp) {
    Write-Host "No app names in Terraform outputs. Is enable_app_hosting true and applied?" -ForegroundColor Red
    exit 1
}

$staging = Join-Path $env:TEMP "asg-deploy"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

# A successful deploy does not prove the new code is serving: Oryx can skip
# the rebuild and the old worker can linger. Stamp the build and refuse to
# report success until /api/health returns this exact value.
$buildId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), (Get-Random -Maximum 9999)

function Deploy-Api {
    Write-Host "Packaging API (build $buildId) ..." -ForegroundColor Cyan
    $src = Join-Path $staging "api"
    New-Item -ItemType Directory -Path (Join-Path $src "services\api") -Force | Out-Null

    Copy-Item (Join-Path $repoRoot "services\api\app") (Join-Path $src "services\api\app") -Recurse
    Copy-Item (Join-Path $repoRoot "services\api\requirements.txt") (Join-Path $src "services\api\")
    Copy-Item (Join-Path $repoRoot "services\api\denylist.txt") (Join-Path $src "services\api\")
    Copy-Item (Join-Path $repoRoot "contracts") (Join-Path $src "contracts") -Recurse
    Copy-Item (Join-Path $repoRoot "agents") (Join-Path $src "agents") -Recurse

    # Oryx installs from the wwwroot root, but the real pins live with the app.
    "-r services/api/requirements.txt" | Set-Content (Join-Path $src "requirements.txt") -NoNewline
    $buildId | Set-Content (Join-Path $src "build_id.txt") -NoNewline

    Get-ChildItem $src -Recurse -Include "__pycache__", "*.pyc", "tests" -Force |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    $zip = Join-Path $staging "api.zip"
    Compress-Archive -Path (Join-Path $src "*") -DestinationPath $zip -Force
    Write-Host "  $([math]::Round((Get-Item $zip).Length / 1MB, 2)) MB"

    Write-Host "Deploying API (Oryx build, this takes a few minutes) ..." -ForegroundColor Cyan
    az webapp deploy --resource-group $resourceGroup --name $apiApp `
        --src-path $zip --type zip --async false -o none
    # Deliberately not fatal. `az webapp deploy` gives up after 10 minutes and
    # reports failure even when the site starts shortly afterwards, and it can
    # also exit 0 while the previous build keeps serving. The build_id check
    # below is the only trustworthy signal, so let it decide.
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  az reported failure; verifying against build_id before believing it." -ForegroundColor Yellow
    }
}

function Deploy-Web {
    Write-Host "Building UI ..." -ForegroundColor Cyan
    Push-Location (Join-Path $repoRoot "apps\web")
    try {
        # No VITE_API_BASE_URL: the browser calls /api on the web tier's own
        # origin and server.js forwards it. Pointing the bundle straight at
        # the API would bypass the proxy, and the API would reject it.
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "UI build failed" }
    } finally {
        Pop-Location
    }

    # server.js sits beside dist/ and is what App Service starts. Shipping
    # only dist/ leaves the site with nothing to run.
    $webStage = Join-Path $staging "web"
    Remove-Item $webStage -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $webStage -Force | Out-Null
    Copy-Item (Join-Path $repoRoot "apps\web\dist") $webStage -Recurse
    Copy-Item (Join-Path $repoRoot "apps\web\server.js") $webStage
    # `"type": "module"` so Node treats server.js as ESM. Without a
    # package.json here the import statements fail at startup.
    '{ "type": "module" }' | Set-Content (Join-Path $webStage "package.json") -NoNewline

    $zip = Join-Path $staging "web.zip"
    Compress-Archive -Path (Join-Path $webStage "*") -DestinationPath $zip -Force
    Write-Host "  $([math]::Round((Get-Item $zip).Length / 1MB, 2)) MB"

    Write-Host "Deploying UI ..." -ForegroundColor Cyan
    az webapp deploy --resource-group $resourceGroup --name $webApp `
        --src-path $zip --type zip --async false -o none
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  az reported failure; verifying the UI actually serves." -ForegroundColor Yellow
    }
}

if ($Only -in @("both", "api")) { Deploy-Api }
if ($Only -in @("both", "web")) { Deploy-Web }

Write-Host ""
Write-Host "Deployed." -ForegroundColor Green
Write-Host "  API : $apiUrl"
Write-Host "  UI  : $webUrl"

# App Service cold start after a zip deploy is slow; poll rather than
# declaring failure on the first attempt.
Write-Host ""
if ($Only -eq "web") {
    Write-Host "Waiting for the UI to serve ..." -NoNewline
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $page = Invoke-WebRequest $webUrl -TimeoutSec 20 -UseBasicParsing
            if ($page.StatusCode -eq 200 -and $page.Content -match 'id="root"') {
                Write-Host ""
                Write-Host "  UI is serving the built bundle." -ForegroundColor Green
                exit 0
            }
        } catch {
            # Not up yet.
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 10
    }
    Write-Host ""
    Write-Host "  UI did not serve index.html after 5 minutes." -ForegroundColor Red
    Write-Host "  Logs: az webapp log tail -g $resourceGroup -n $webApp" -ForegroundColor Yellow
    exit 1
}

Write-Host "Waiting for build $buildId to serve ..." -NoNewline
$served = $null
$sawHealthWithoutBuildId = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $h = Invoke-RestMethod "$apiUrl/api/health" -TimeoutSec 20
        $served = $h.build_id
        if ($served -eq $buildId) {
            Write-Host ""
            Write-Host "  status   = $($h.status)" -ForegroundColor Green
            Write-Host "  build_id = $served" -ForegroundColor Green
            exit 0
        }
        # An older deployment predates the build stamp entirely.
        if (-not $served) { $sawHealthWithoutBuildId = $true }
    } catch {
        # Not up yet; fall through to the sleep below.
    }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 10
}
Write-Host ""
if ($sawHealthWithoutBuildId) {
    Write-Host "  API is healthy but reports no build_id." -ForegroundColor Red
    Write-Host "  The running build predates build stamping, so it is stale." -ForegroundColor Red
} elseif ($served) {
    Write-Host "  DEPLOY REPORTED SUCCESS BUT STALE CODE IS SERVING." -ForegroundColor Red
    Write-Host "  expected build_id $buildId, got $served" -ForegroundColor Red
    Write-Host "  Try: az webapp restart -g $resourceGroup -n $apiApp" -ForegroundColor Yellow
} else {
    Write-Host "  API never became healthy. The site is down." -ForegroundColor Red
}
Write-Host "  Logs: az webapp log tail -g $resourceGroup -n $apiApp" -ForegroundColor Yellow
exit 1
