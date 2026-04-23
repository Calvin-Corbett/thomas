[CmdletBinding()]
param(
    [string]$FocusAgent = "thomas",
    [int]$TopGaps = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
Invoke-AgentComparisonSuite -RepoRoot $repoRoot -FocusAgent $FocusAgent -TopGaps $TopGaps -NoRegistryWrite
Write-Output "Quick suite completed without artifact writes."
