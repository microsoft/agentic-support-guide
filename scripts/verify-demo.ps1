# Verify customer demo readiness end-to-end.
#
# Runs a checklist of presence-only checks. Never prints secret values,
# endpoints, connection strings, or raw env values.
#
# Exit codes:
#   0 - demo ready
#   1 - one or more required checks failed
#
# Usage:  .\scripts\verify-demo.ps1
#         .\scripts\verify-demo.ps1 -SkipRecommendation   # skip live LLM call

param(
    [switch]$SkipRecommendation
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$baseUrl  = if ($env:API_BASE_URL) { $env:API_BASE_URL } else { "http://127.0.0.1:8000" }

$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$name, [bool]$ok, [string]$detail) {
    $results.Add([pscustomobject]@{ name = $name; ok = $ok; detail = $detail })
}

# 1. Terraform state present (proxy for "apply has run at least once").
$tfstate = Join-Path $repoRoot "infra\terraform.tfstate"
Add-Result "terraform_state_present" (Test-Path $tfstate) `
    "$([IO.Path]::GetFileName($tfstate)) exists in infra/"

# 2. Backend .env present with all required keys (presence-only, values hidden).
$envFile = Join-Path $repoRoot "services\api\.env"
$envRequired = @(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
    "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
    "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
    "AZURE_AI_FOUNDRY_AUTH_MODE"
)
if (Test-Path $envFile) {
    $envLines = Get-Content $envFile
    $missing = @()
    foreach ($key in $envRequired) {
        $match = $envLines | Where-Object { $_ -match "^\s*$key\s*=\s*(.+)\s*$" }
        if (-not $match) { $missing += $key }
    }
    if ($missing.Count -eq 0) {
        Add-Result "env_keys_present" $true "all required AZURE_AI_FOUNDRY_* keys populated"
    } else {
        Add-Result "env_keys_present" $false "missing: $($missing -join ', ')"
    }
} else {
    Add-Result "env_keys_present" $false "services/api/.env not found"
}

# 3. Frontend node_modules present.
$nodeModules = Join-Path $repoRoot "apps\web\node_modules"
Add-Result "frontend_deps_installed" (Test-Path $nodeModules) "apps/web/node_modules exists"

# 4-6. Backend reachable + /api/health/details + customer_demo_ready.
$health = $null
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/api/health/details" -Method Get -TimeoutSec 5
    Add-Result "backend_reachable" $true "$baseUrl responded"
} catch {
    Add-Result "backend_reachable" $false "backend unreachable at $baseUrl"
}

if ($health) {
    Add-Result "active_provider_azure_foundry_responses" `
        ($health.active_provider -eq "azure_foundry_responses") `
        "active_provider = $($health.active_provider)"
    Add-Result "customer_demo_ready" ([bool]$health.customer_demo_ready) `
        "customer_demo_ready = $($health.customer_demo_ready)"
    Add-Result "foundry_project_configured" ([bool]$health.foundry_project_configured) `
        "foundry_project_configured = $($health.foundry_project_configured)"
    Add-Result "agent_definitions_valid" ([bool]$health.agent_definitions_valid) `
        "agent_definitions_valid = $($health.agent_definitions_valid)"
    Add-Result "service_side_remote_workflow_active" ([bool]$health.service_side_remote_workflow_active) `
        "service_side_remote_workflow_active = $($health.service_side_remote_workflow_active)"
}

# 7. Recommendation endpoint works end-to-end using synthetic data.
if (-not $SkipRecommendation -and $health -and $health.customer_demo_ready) {
    $recBody = @{
        dealer_group_id = "GROUP-A"
        dealership_id   = "DLR-0001"
        category        = "lead-response"
        concern_text    = "First response to online enquiries is slower than the standard."
    } | ConvertTo-Json

    # Role assignments created moments ago may not have propagated, so a
    # correct deployment can fail this check once. Retry on auth failures
    # only; anything else is a real fault and should fail immediately.
    $delays = @(0, 20, 40, 60)
    $ok = $false
    $detail = ""
    foreach ($delay in $delays) {
        if ($delay -gt 0) {
            Write-Host "  waiting ${delay}s for role assignments to propagate ..."
            Start-Sleep -Seconds $delay
        }
        try {
            $rec = Invoke-RestMethod -Uri "$baseUrl/api/recommendations/support-plan" `
                -Method Post -Body $recBody -ContentType "application/json" -TimeoutSec 60
            $ok = ($rec.status -eq "ok" -and $null -ne $rec.recommendation)
            $detail = "status = $($rec.status)"
            if ($ok) { break }
            if ($rec.error_code -notlike "*AUTH*") { break }
        } catch {
            $detail = "recommendation call failed: $($_.Exception.Message)"
        }
    }
    Add-Result "recommendation_ok" $ok $detail
} elseif ($SkipRecommendation) {
    Add-Result "recommendation_ok" $true "skipped (--SkipRecommendation)"
}

# --- Print report ---
Write-Host ""
Write-Host "Customer demo readiness" -ForegroundColor Cyan
Write-Host "-----------------------"
$allOk = $true
foreach ($r in $results) {
    $mark  = if ($r.ok) { "[ok]  " } else { "[FAIL]" }
    $color = if ($r.ok) { "Green" } else { "Red" }
    Write-Host "$mark $($r.name.PadRight(34)) $($r.detail)" -ForegroundColor $color
    if (-not $r.ok) { $allOk = $false }
}

if ($health -and $health.warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Warnings from /api/health/details:" -ForegroundColor Yellow
    foreach ($w in $health.warnings) { Write-Host "  - $w" }
}

Write-Host ""
if ($allOk) {
    Write-Host "Ready for customer demo." -ForegroundColor Green
    exit 0
} else {
    Write-Host "NOT ready. Fix the [FAIL] items above before the demo." -ForegroundColor Red
    exit 1
}

