[CmdletBinding()]
param(
    [string]$FocusAgent = "thomas",
    [int]$TopGaps = 120,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
Invoke-AgentComparisonSuite -RepoRoot $repoRoot -FocusAgent $FocusAgent -TopGaps $TopGaps -Write -WriteMd -Json:$Json

$paths = Get-AgentSuitePaths -RepoRoot $repoRoot
Write-Output "Suite artifacts updated:"
Write-Output "- $($paths.LatestJson)"
Write-Output "- $($paths.LatestMd)"
