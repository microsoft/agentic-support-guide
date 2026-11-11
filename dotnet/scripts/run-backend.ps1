# Starts the ASP.NET Core backend, restarting it when the code changes.
$ErrorActionPreference = "Stop"
$trackRoot = Split-Path -Parent $PSScriptRoot
$api = Join-Path $trackRoot "services\api\AgenticSupportGuide.Api"
$envPath = Join-Path $trackRoot "services\api\.env"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Warning "No dotnet found. Install the .NET 10 SDK first."
    exit 1
}

if (-not (Test-Path $envPath)) {
    Write-Warning "No dotnet/services/api/.env found. Run .\dotnet\scripts\populate-env.ps1 first, or the backend will start unconfigured."
} else {
    # Like uvicorn's --env-file: a variable already set in this shell wins.
    foreach ($raw in Get-Content $envPath) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $value.Trim())
        }
    }
}

$env:ASPNETCORE_URLS = "http://127.0.0.1:8000"
dotnet watch --non-interactive --project $api run
