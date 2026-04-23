[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$paths = Get-AgentSuitePaths -RepoRoot $repoRoot
$result = Read-LatestSuiteResult -RepoRoot $repoRoot

if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot "docs\openclaw_gap_runs\latest_full_suite_summary.csv"
}

$rows = @($result.scoreboard.ranking | ForEach-Object {
    [pscustomobject]@{
        computed_at_utc = [string]$result.computed_at_utc
        agent = [string]$_.agent
        rank = [int]$_.rank
        composite_score = [double]$_.composite_score
        wins = [int]$_.wins
        metrics_with_data = [int]$_.metrics_with_data
        comparable_metrics_with_data = [int]$_.comparable_metrics_with_data
    }
})

$parent = Split-Path -Path $OutputPath -Parent
if ($parent -and -not (Test-Path $parent)) {
    New-Item -Path $parent -ItemType Directory -Force | Out-Null
}

$rows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding utf8
Write-Output "Wrote suite summary CSV: $OutputPath"
