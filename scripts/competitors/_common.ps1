Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ThomasRepoRoot {
    param(
        [string]$StartPath = $PSScriptRoot
    )
    $resolved = Resolve-Path (Join-Path $StartPath "..\..")
    return $resolved.ProviderPath
}

function Get-ThomasPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    if ($env:THOMAS_PYTHON -and (Test-Path $env:THOMAS_PYTHON)) {
        return $env:THOMAS_PYTHON
    }
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    throw "Python was not found. Set THOMAS_PYTHON or install python."
}

function Get-AgentSuitePaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    return @{
        RepoRoot      = $RepoRoot
        SuiteConfig   = Join-Path $RepoRoot "demo\baselines\agent_comparison_suite.current.json"
        RunnerScript  = Join-Path $RepoRoot "scripts\run_agent_comparison_suite.py"
        LatestJson    = Join-Path $RepoRoot "docs\openclaw_gap_runs\latest_full_suite_compare.json"
        LatestMd      = Join-Path $RepoRoot "docs\openclaw_gap_runs\latest_full_suite_compare.md"
        LatestLegacy  = Join-Path $RepoRoot "docs\openclaw_gap_runs\latest_compare.json"
        RegistryJson  = Join-Path $RepoRoot "docs\openclaw_gap_runs\competitor_registry.json"
        RegistryMd    = Join-Path $RepoRoot "docs\openclaw_gap_runs\competitor_registry.md"
    }
}

function Invoke-AgentComparisonSuite {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string]$FocusAgent = "thomas",
        [int]$TopGaps = 25,
        [switch]$Write,
        [switch]$WriteMd,
        [switch]$Json,
        [switch]$NoRegistryWrite,
        [string[]]$ExtraArgs = @()
    )
    $paths = Get-AgentSuitePaths -RepoRoot $RepoRoot
    $python = Get-ThomasPython -RepoRoot $RepoRoot
    $args = @(
        $paths.RunnerScript,
        "--suite-config", $paths.SuiteConfig,
        "--focus-agent", $FocusAgent,
        "--top-gaps", "$TopGaps"
    )
    if ($Write) {
        $args += @("--write", "--write-path", $paths.LatestJson)
    }
    if ($WriteMd) {
        $args += @("--write-md", "--write-md-path", $paths.LatestMd)
    }
    if ($Json) {
        $args += "--json"
    }
    if ($NoRegistryWrite) {
        $args += "--no-registry-write"
    }
    if ($ExtraArgs) {
        $args += $ExtraArgs
    }

    & $python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Agent comparison suite failed with exit code $LASTEXITCODE."
    }
}

function Read-LatestSuiteResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    $paths = Get-AgentSuitePaths -RepoRoot $RepoRoot
    if (-not (Test-Path $paths.LatestJson)) {
        throw "Missing latest suite result at '$($paths.LatestJson)'. Run run-full-suite.ps1 first."
    }
    return Get-Content $paths.LatestJson -Raw | ConvertFrom-Json
}
