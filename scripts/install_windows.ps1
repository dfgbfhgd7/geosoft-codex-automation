[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Venv = ".venv",
    [switch]$InstallForCodex,
    [string]$CodexHome = (Join-Path $HOME ".codex")
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($InstallForCodex) {
    $skillRoot = Join-Path $CodexHome "skills\geosoft-automation"
    $configPath = Join-Path $CodexHome "config.toml"
    $sectionPattern = '(?m)^\s*\[mcp_servers\.geosoft-automation\]\s*$'

    if (Test-Path -LiteralPath $skillRoot) {
        throw "Refusing to overwrite existing Skill directory: $skillRoot"
    }
    if ((Test-Path -LiteralPath $configPath) -and
        ((Get-Content -LiteralPath $configPath -Raw) -match $sectionPattern)) {
        throw "MCP section already exists in $configPath"
    }

    New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
    foreach ($directory in @("agents", "assets", "references", "scripts")) {
        New-Item -ItemType Directory -Path (Join-Path $skillRoot $directory) -Force | Out-Null
    }

    $files = @(
        "SKILL.md",
        "agents\openai.yaml",
        "assets\icon.svg",
        "references\compatibility.md",
        "references\aeromagnetic-review.md",
        "scripts\geosoft_mcp.py",
        "scripts\aeromag_auto_review.py",
        "scripts\requirements.txt"
    )
    foreach ($relativePath in $files) {
        $sourcePath = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Required Skill file is missing: $sourcePath"
        }
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $skillRoot $relativePath)
    }

    $pythonCommand = (Get-Command $Python -ErrorAction Stop).Source
    & $pythonCommand -B (Join-Path $skillRoot "scripts\geosoft_mcp.py") --self-test
    if ($LASTEXITCODE -ne 0) {
        throw "Installed MCP self-test failed"
    }

    New-Item -ItemType Directory -Path $CodexHome -Force | Out-Null
    if (Test-Path -LiteralPath $configPath) {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        Copy-Item -LiteralPath $configPath -Destination "$configPath.$timestamp.bak"
    } else {
        New-Item -ItemType File -Path $configPath -Force | Out-Null
    }

    function ConvertTo-TomlLiteral([string]$Value) {
        return "'" + $Value.Replace("'", "''") + "'"
    }
    $serverPath = Join-Path $skillRoot "scripts\geosoft_mcp.py"
    $block = @(
        "",
        "[mcp_servers.geosoft-automation]",
        "command = $(ConvertTo-TomlLiteral $pythonCommand)",
        "args = [$(ConvertTo-TomlLiteral $serverPath), '--serve']",
        "startup_timeout_sec = 120",
        ""
    ) -join [Environment]::NewLine
    Add-Content -LiteralPath $configPath -Value $block -Encoding UTF8

    Write-Host "Installed Skill: $skillRoot"
    Write-Host "Registered MCP: geosoft-automation"
    Write-Host "Config backup was created when an existing config.toml was present."
    Write-Host "Restart Codex, then test the MCP tools on a new dataset."
    return
}

$venvPath = Join-Path $repoRoot $Venv

& $Python -m venv $venvPath
$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython (Join-Path $PSScriptRoot "geosoft_mcp.py") --self-test

Write-Host "Created: $venvPath"
Write-Host "MCP command: $venvPython"
Write-Host "MCP args: $(Join-Path $PSScriptRoot 'geosoft_mcp.py') --serve"
Write-Host "Next: & '$venvPython' '$(Join-Path $PSScriptRoot 'geosoft_mcp.py')' --detect"
