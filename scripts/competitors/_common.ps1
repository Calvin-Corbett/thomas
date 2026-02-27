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

function Resolve-AgentSuiteArtifactPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string]$ConfiguredPath = "",
        [Parameter(Mandatory = $true)]
        [string]$DefaultRelativePath
    )
    $value = [string]$ConfiguredPath
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = $DefaultRelativePath
    }
    if (-not [System.IO.Path]::IsPathRooted($value)) {
        $value = Join-Path $RepoRoot $value
    }
    return [System.IO.Path]::GetFullPath($value)
}

function Get-AgentSuitePaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    $suiteConfigPath = Join-Path $RepoRoot "demo\baselines\agent_comparison_suite.current.json"
    $artifactPaths = $null
    if (Test-Path $suiteConfigPath) {
        try {
            $suiteConfig = Get-Content $suiteConfigPath -Raw | ConvertFrom-Json
            if ($suiteConfig -and $suiteConfig.artifact_paths) {
                $artifactPaths = $suiteConfig.artifact_paths
            }
        }
        catch {
            $artifactPaths = $null
        }
    }

    return @{
        RepoRoot      = $RepoRoot
        SuiteConfig   = $suiteConfigPath
        RunnerScript  = Join-Path $RepoRoot "scripts\run_agent_comparison_suite.py"
        LatestJson    = Resolve-AgentSuiteArtifactPath -RepoRoot $RepoRoot -ConfiguredPath $artifactPaths.latest_json -DefaultRelativePath "docs\openclaw_gap_runs\latest_full_suite_compare.json"
        LatestMd      = Resolve-AgentSuiteArtifactPath -RepoRoot $RepoRoot -ConfiguredPath $artifactPaths.latest_markdown -DefaultRelativePath "docs\openclaw_gap_runs\latest_full_suite_compare.md"
        LatestLegacy  = Resolve-AgentSuiteArtifactPath -RepoRoot $RepoRoot -ConfiguredPath $artifactPaths.latest_legacy_json -DefaultRelativePath "docs\openclaw_gap_runs\latest_compare.json"
        RegistryJson  = Resolve-AgentSuiteArtifactPath -RepoRoot $RepoRoot -ConfiguredPath $artifactPaths.registry_json -DefaultRelativePath "docs\openclaw_gap_runs\competitor_registry.json"
        RegistryMd    = Resolve-AgentSuiteArtifactPath -RepoRoot $RepoRoot -ConfiguredPath $artifactPaths.registry_markdown -DefaultRelativePath "docs\openclaw_gap_runs\competitor_registry.md"
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
    else {
        $args += @("--registry-path", $paths.RegistryJson, "--registry-md-path", $paths.RegistryMd)
    }
    if ($ExtraArgs) {
        $args += $ExtraArgs
    }

    & $python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Agent comparison suite failed with exit code $LASTEXITCODE."
    }

    if ($Write -and (Test-Path $paths.LatestJson)) {
        $latestJson = [System.IO.Path]::GetFullPath($paths.LatestJson)
        $latestLegacy = [System.IO.Path]::GetFullPath($paths.LatestLegacy)
        if (-not ($latestJson -ieq $latestLegacy)) {
            $legacyDir = Split-Path $paths.LatestLegacy -Parent
            if (-not [string]::IsNullOrWhiteSpace($legacyDir)) {
                New-Item -ItemType Directory -Force -Path $legacyDir | Out-Null
            }
            Copy-Item -Path $paths.LatestJson -Destination $paths.LatestLegacy -Force
        }
    }
}

function Read-LatestSuiteResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    $paths = Get-AgentSuitePaths -RepoRoot $RepoRoot
    $resultPath = $paths.LatestJson
    if (-not (Test-Path $resultPath)) {
        if (Test-Path $paths.LatestLegacy) {
            $resultPath = $paths.LatestLegacy
        }
        else {
            throw "Missing latest suite result at '$($paths.LatestJson)' (legacy fallback: '$($paths.LatestLegacy)'). Run run-full-suite.ps1 first."
        }
    }
    return Get-Content $resultPath -Raw | ConvertFrom-Json
}
