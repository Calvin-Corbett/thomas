Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$paths = Get-AgentSuitePaths -RepoRoot $repoRoot

$config = Get-Content $paths.SuiteConfig -Raw | ConvertFrom-Json
$catalog = @($config.competitor_catalog)

$registry = @{}
if (Test-Path $paths.RegistryJson) {
    $registry = (Get-Content $paths.RegistryJson -Raw | ConvertFrom-Json).competitors
}

$rows = @()
foreach ($entry in $catalog) {
    $id = [string]$entry.id
    $reg = $null
    if ($registry -and $registry.PSObject.Properties.Name -contains $id) {
        $reg = $registry.$id
    }
    $localHead = ""
    $isUpToDate = ""
    $modelDay = ""
    $lastTestAt = ""
    if ($reg) {
        if ($reg.version -and ($reg.version.PSObject.Properties.Name -contains "local_head")) {
            $localHead = [string]$reg.version.local_head
        }
        if ($reg.version -and ($reg.version.PSObject.Properties.Name -contains "is_up_to_date")) {
            $isUpToDate = [string]$reg.version.is_up_to_date
        }
        if ($reg.model_snapshot -and ($reg.model_snapshot.PSObject.Properties.Name -contains "day_utc")) {
            $modelDay = [string]$reg.model_snapshot.day_utc
        }
        if ($reg.PSObject.Properties.Name -contains "last_tested_at_utc") {
            $lastTestAt = [string]$reg.last_tested_at_utc
        }
    }
    $rows += [pscustomobject]@{
        id = $id
        label = [string]$entry.label
        enabled = [bool]$entry.enabled
        root = [string]$entry.root
        branch = [string]$entry.branch
        local_head = $localHead
        is_up_to_date = $isUpToDate
        model_day_utc = $modelDay
        last_test_at_utc = $lastTestAt
    }
}

if (-not $rows) {
    Write-Output "No competitors found in suite config."
    exit 0
}

$rows | Format-Table -AutoSize
