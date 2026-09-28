[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Venv = ".venv"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot $Venv

& $Python -m venv $venvPath
$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython (Join-Path $PSScriptRoot "geosoft_mcp.py") --self-test

Write-Host "Created: $venvPath"
Write-Host "MCP command: $venvPython"
Write-Host "MCP args: $(Join-Path $PSScriptRoot 'geosoft_mcp.py') --serve"
Write-Host "Next: & '$venvPython' '$(Join-Path $PSScriptRoot 'geosoft_mcp.py')' --detect"
