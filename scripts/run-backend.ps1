# Starts the FastAPI backend. Activates .venv if present.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$api = Join-Path $repoRoot "services\api"
Set-Location $api

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
} else {
    Write-Warning "No .venv found. Run 'py -3.13 -m venv .venv' inside services/api first."
    exit 1
}

if (-not (Test-Path ".\.env")) {
    Write-Warning "No services/api/.env found. Run .\scripts\populate-env.ps1 first, or the backend will start unconfigured."
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
} else {
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --env-file .env
}
