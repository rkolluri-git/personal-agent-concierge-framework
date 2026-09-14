$ErrorActionPreference = 'Stop'
# Run checks in a child process so its exit statement cannot skip startup here.
& (Get-Process -Id $PID).Path -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location (Split-Path -Parent $PSScriptRoot)
& docker compose up -d --build
exit $LASTEXITCODE
