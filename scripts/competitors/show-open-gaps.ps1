[CmdletBinding()]
param(
    [int]$Limit = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$result = Read-LatestSuiteResult -RepoRoot $repoRoot
$gaps = @($result.focus.open_gaps)

if (-not $gaps) {
    Write-Output "No open gaps in latest result."
    exit 0
}

$gaps |
    Select-Object -First $Limit |
    Select-Object metric, category, weight, winners, gap_to_best |
    Format-Table -AutoSize
