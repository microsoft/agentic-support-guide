# Regenerate docs/architecture.svg from docs/architecture.dsl.
#
# Prefers structurizr-cli (Java-based). Structurizr CLI does not emit SVG
# directly; this script exports the model to PlantUML and then converts the
# .puml file to SVG with the PlantUML CLI.
#
# If either CLI is missing, the script exits with a clear installation hint
# and leaves the committed docs/architecture.svg untouched so GitHub still
# renders the current version.

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$dsl      = Join-Path $repoRoot 'docs\architecture.dsl'
$svg      = Join-Path $repoRoot 'docs\architecture.svg'
$staging  = Join-Path $repoRoot 'docs\.render-staging'

if (-not (Test-Path $dsl)) {
    Write-Host "Missing DSL source: $dsl" -ForegroundColor Red
    exit 1
}

function Find-Cli([string[]]$names) {
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd }
    }
    return $null
}

$structurizr = Find-Cli @('structurizr-cli', 'structurizr')
if ($null -eq $structurizr) {
    Write-Host ""
    Write-Host "No Structurizr-compatible CLI found on PATH." -ForegroundColor Yellow
    Write-Host "Install one of the following, then re-run this script:" -ForegroundColor Yellow
    Write-Host "  - structurizr-cli (Java-based, from the Structurizr project)"
    Write-Host "  - a container runtime plus the 'structurizr/cli' image"
    Write-Host ""
    Write-Host "The committed docs/architecture.svg has been left in place."
    exit 2
}

$plantuml = Find-Cli @('plantuml')
if ($null -eq $plantuml) {
    Write-Host ""
    Write-Host "PlantUML CLI not found on PATH." -ForegroundColor Yellow
    Write-Host "Structurizr CLI exports to PlantUML; PlantUML converts that to SVG."
    Write-Host "Install PlantUML (https://plantuml.com) and re-run this script."
    Write-Host "The committed docs/architecture.svg has been left in place."
    exit 3
}

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

Write-Host "Exporting DSL to PlantUML..."
& $structurizr.Path export -workspace $dsl -format plantuml -output $staging

$puml = Get-ChildItem -Path $staging -Filter '*.puml' | Select-Object -First 1
if ($null -eq $puml) {
    Write-Host "Structurizr CLI did not produce a .puml file." -ForegroundColor Red
    exit 4
}

Write-Host "Converting PlantUML to SVG..."
& $plantuml.Path -tsvg $puml.FullName -o $staging | Out-Null

$producedSvg = Get-ChildItem -Path $staging -Filter '*.svg' | Select-Object -First 1
if ($null -eq $producedSvg) {
    Write-Host "PlantUML did not produce an .svg file." -ForegroundColor Red
    exit 5
}

Copy-Item -Force $producedSvg.FullName $svg
Remove-Item -Recurse -Force $staging

Write-Host "Wrote docs/architecture.svg" -ForegroundColor Green
Write-Host "Commit both docs/architecture.dsl and docs/architecture.svg so GitHub renders the latest diagram."
