[CmdletBinding()]
param(
    [double]$MaxAgeDays = 7,
    [string]$Now = "",
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$python = Get-ThomasPython -RepoRoot $repoRoot
$scriptPath = Join-Path $repoRoot "scripts\check_competitor_freshness_guard.py"

$args = @(
    $scriptPath,
    "--max-age-days", "$MaxAgeDays"
)
if ([string]::IsNullOrWhiteSpace($Now) -eq $false) {
    $args += @("--now", $Now)
}
if ($Json) {
    $args += "--json"
}

& $python @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
