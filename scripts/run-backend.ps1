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

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
