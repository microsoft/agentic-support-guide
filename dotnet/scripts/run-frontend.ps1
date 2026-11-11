# Starts the Vite dev server.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location (Join-Path $repoRoot "apps\web")
npm run dev
