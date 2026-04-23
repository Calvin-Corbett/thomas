[CmdletBinding()]
param(
    [string]$FocusAgent = "thomas",
    [int]$TopGaps = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
Invoke-AgentComparisonSuite -RepoRoot $repoRoot -FocusAgent $FocusAgent -TopGaps $TopGaps -Write -WriteMd

$result = Read-LatestSuiteResult -RepoRoot $repoRoot
$prepared = @($result.preparation)
Write-Output "Competitor refresh status:"
$prepared | Select-Object id, status, root | Format-Table -AutoSize
