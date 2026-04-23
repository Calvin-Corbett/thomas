[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Id,
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [string]$Branch = "main",
    [switch]$Disabled
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$paths = Get-AgentSuitePaths -RepoRoot $repoRoot
$configPath = $paths.SuiteConfig
$payload = Get-Content $configPath -Raw | ConvertFrom-Json

if (-not $payload.competitor_catalog) {
    $payload | Add-Member -MemberType NoteProperty -Name "competitor_catalog" -Value @()
}

$catalog = @($payload.competitor_catalog)
$match = $catalog | Where-Object { [string]$_.id -eq $Id } | Select-Object -First 1
$row = [pscustomobject]@{
    id = $Id
    label = $Label
    repo_url = $RepoUrl
    root = $Root
    branch = $Branch
    enabled = (-not $Disabled)
}

if ($match) {
    $updated = @()
    foreach ($entry in $catalog) {
        if ([string]$entry.id -eq $Id) {
            $updated += $row
        } else {
            $updated += $entry
        }
    }
    $payload.competitor_catalog = $updated
    $mode = "updated"
} else {
    $payload.competitor_catalog += $row
    $mode = "added"
}

$json = $payload | ConvertTo-Json -Depth 100
Set-Content -Path $configPath -Value $json -Encoding utf8
Write-Output "Competitor '$Id' $mode in suite config: $configPath"
