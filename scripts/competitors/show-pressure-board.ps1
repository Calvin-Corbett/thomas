Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$result = Read-LatestSuiteResult -RepoRoot $repoRoot
$rows = @($result.focus.competitor_pressure.ranked_competitors)
if (-not $rows) {
    Write-Output "No pressure board data found in latest suite result."
    exit 0
}

$rows |
    Select-Object competitor, threat_level, composite_score, composite_delta_vs_focus, metrics_beating_focus, metrics_focus_beats, metrics_tied |
    Format-Table -AutoSize
