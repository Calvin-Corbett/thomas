[CmdletBinding()]
param(
    [string]$ExpectedDayUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$result = Read-LatestSuiteResult -RepoRoot $repoRoot
$agents = @($result.agents)
$failures = @()

foreach ($agent in $agents) {
    $id = [string]$agent.id
    $snap = $agent.model_snapshot
    if (-not $snap) {
        continue
    }
    $required = [bool]$snap.required
    if (-not $required) {
        continue
    }
    if (-not [bool]$snap.ok) {
        $failures += "${id}: required snapshot not ok ($($snap.error))"
        continue
    }
    if ([string]$snap.day_utc -ne $ExpectedDayUtc) {
        $failures += "${id}: day_utc '$($snap.day_utc)' != '$ExpectedDayUtc'"
    }
}

if ($failures.Count -gt 0) {
    Write-Output "Model snapshot validation failed:"
    $failures | ForEach-Object { Write-Output "- $_" }
    exit 2
}

Write-Output "Model snapshot validation passed for required agents (day_utc=$ExpectedDayUtc)."
