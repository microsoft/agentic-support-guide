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
}

# Like uvicorn's --env-file: the .env values reach the backend only, a
# variable already set in this shell wins, and nothing is left behind in the
# shell when the backend stops -- so blanking a line in .env and restarting
# really does unset it.
$saved = @{}
try {
    if (Test-Path $envPath) {
        foreach ($raw in Get-Content $envPath) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
            $key, $value = $line.Split("=", 2)
            $key = $key.Trim()
            if (-not [Environment]::GetEnvironmentVariable($key)) {
                $saved[$key] = $null
                [Environment]::SetEnvironmentVariable($key, $value.Trim())
            }
        }
    }
    $saved["ASPNETCORE_URLS"] = $env:ASPNETCORE_URLS
    $env:ASPNETCORE_URLS = "http://127.0.0.1:8000"

    # Built into its own folder: the running app locks the files it was built
    # to, so sharing bin\ would make every `dotnet test` or IDE build fail while
    # the backend runs.
    dotnet watch --non-interactive --project $api --artifacts-path (Join-Path $api "obj\watch") run
} finally {
    foreach ($key in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($key, $saved[$key])
    }
}
