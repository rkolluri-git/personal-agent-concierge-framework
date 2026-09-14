# Native PowerShell prerequisite checks. Does not install software or send messages.
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir
$failures = 0
function Fail([string]$text) { Write-Host "FAIL  $text"; $script:failures++ }
if (-not (Test-Path .env -PathType Leaf)) {
    Fail 'Copy .env.example to .env and set a unique password and regional settings.'
} elseif ((Get-Content .env -Raw) -match 'replace-with-a-long-random-password') {
    Fail 'Replace the example database password.'
}
$selectedProvider = $env:FAMILY_MESSAGING_PROVIDER
if (-not $selectedProvider -and (Test-Path .env -PathType Leaf)) {
    foreach ($line in Get-Content .env) {
        if ($line -match '^\s*FAMILY_MESSAGING_PROVIDER\s*=\s*(.*?)\s*$') {
            $selectedProvider = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}
if ($selectedProvider -and $selectedProvider -ne 'imessage') {
    if ($selectedProvider -notin @('twilio-sms','twilio-whatsapp','openclaw')) { Fail 'Unsupported messaging provider.' }
    if (-not (Test-Path config/messaging.json -PathType Leaf)) { Fail 'Create private config/messaging.json from the matching example.' }
}
foreach ($file in @('Dockerfile','docker-compose.yml','backend/requirements.txt')) {
    if (-not (Test-Path $file -PathType Leaf)) { Fail "Missing package file: $file" }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail 'Install Docker Desktop with Linux containers and start it.'
} else {
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'Docker Compose v2 is unavailable.' }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'Start Docker Desktop and check Docker permissions.' }
    & docker compose config --quiet *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'Compose configuration is invalid; check .env and POSTGRES_PASSWORD.' }
}
Write-Host 'NOTE  Host Python/PostgreSQL are unnecessary for Docker. Initial downloads need internet.'
Write-Host 'NOTE  OpenClaw adapter runs alongside OpenClaw in WSL; iMessage and Apple Maps require macOS.'
if ($failures -gt 0) { Write-Host "$failures required checks failed."; exit 1 }
Write-Host 'Required Windows dependency checks passed. Provider setup is separate; see MESSAGING_SETUP.md.'
exit 0
