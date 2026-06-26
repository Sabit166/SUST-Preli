# Launch the SUST-Preli FastAPI service.
#
# Usage (from any cwd in PowerShell):
#   .\run.ps1                # bind 0.0.0.0:8000
#   .\run.ps1 -Port 8765     # bind 0.0.0.0:8765
#   .\run.ps1 -Host 127.0.0.1 -Port 8765
#
# The script always switches to this file's directory before starting uvicorn,
# so the "Could not import module 'main'" error from a wrong cwd can't recur.

[CmdletBinding()]
param(
    # NOTE: not named $Host — that's a read-only automatic variable in PowerShell.
    [string]$BindHost = '0.0.0.0',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

# Resolve and switch to the project root (this script's folder).
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

Write-Host "[run.ps1] cwd       = $PWD" -ForegroundColor DarkGray
Write-Host "[run.ps1] launching uvicorn on http://${BindHost}:${Port}" -ForegroundColor Cyan

uvicorn main:app --host $BindHost --port $Port