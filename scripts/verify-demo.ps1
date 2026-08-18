# Prints customer_demo_ready and active_provider from /api/health/details.
$ErrorActionPreference = "Stop"
$baseUrl = if ($env:API_BASE_URL) { $env:API_BASE_URL } else { "http://127.0.0.1:8000" }

try {
    $body = Invoke-RestMethod -Uri "$baseUrl/api/health/details" -Method Get -TimeoutSec 5
} catch {
    Write-Host "API unavailable at $baseUrl. Start the backend and try again." -ForegroundColor Red
    exit 1
}

$ready = $body.customer_demo_ready
$color = if ($ready) { "Green" } else { "Yellow" }
Write-Host "active_provider     : $($body.active_provider)"
Write-Host "customer_demo_ready : $ready" -ForegroundColor $color
Write-Host "guidance            : $($body.guidance)"

foreach ($check in $body.checks) {
    $mark = if ($check.ok) { "[ok]  " } else { "[todo]" }
    Write-Host "$mark $($check.label) - $($check.detail)"
}

if ($body.warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Warnings:" -ForegroundColor Yellow
    foreach ($w in $body.warnings) { Write-Host "  - $w" }
}

if (-not $ready) { exit 2 }
