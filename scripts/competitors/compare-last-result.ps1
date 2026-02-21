Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$paths = Get-AgentSuitePaths -RepoRoot $repoRoot

if (-not (Test-Path $paths.LatestJson)) {
    throw "Missing latest full suite result: $($paths.LatestJson)"
}
if (-not (Test-Path $paths.LatestLegacy)) {
    throw "Missing previous compare result: $($paths.LatestLegacy)"
}

$current = Get-Content $paths.LatestJson -Raw | ConvertFrom-Json
$previous = Get-Content $paths.LatestLegacy -Raw | ConvertFrom-Json

$currentRanking = @()
if (($current.PSObject.Properties.Name -contains "scoreboard") -and $current.scoreboard -and $current.scoreboard.ranking) {
    $currentRanking = @($current.scoreboard.ranking)
}
if (-not $currentRanking) {
    throw "Latest full suite result has no scoreboard ranking."
}

$previousRanking = @()
if (($previous.PSObject.Properties.Name -contains "scoreboard") -and $previous.scoreboard -and $previous.scoreboard.ranking) {
    $previousRanking = @($previous.scoreboard.ranking)
} elseif (($previous.PSObject.Properties.Name -contains "ranking") -and $previous.ranking) {
    $previousRanking = @($previous.ranking)
}
if (-not $previousRanking) {
    Write-Output "Previous result does not include scoreboard ranking. No rank delta available."
    exit 0
}

$currentRanks = @{}
foreach ($row in $currentRanking) {
    $currentRanks[[string]$row.agent] = $row
}
$previousRanks = @{}
foreach ($row in $previousRanking) {
    $previousRanks[[string]$row.agent] = $row
}

$agents = @($currentRanks.Keys + $previousRanks.Keys | Sort-Object -Unique)
$rows = @()
foreach ($agent in $agents) {
    $cur = $null
    $prev = $null
    if ($currentRanks.ContainsKey($agent)) { $cur = $currentRanks[$agent] }
    if ($previousRanks.ContainsKey($agent)) { $prev = $previousRanks[$agent] }
    $rows += [pscustomobject]@{
        agent = $agent
        current_score = if ($cur) { [double]$cur.composite_score } else { $null }
        previous_score = if ($prev) { [double]$prev.composite_score } else { $null }
        score_delta = if ($cur -and $prev) { [math]::Round(([double]$cur.composite_score - [double]$prev.composite_score), 3) } else { $null }
        current_rank = if ($cur) { [int]$cur.rank } else { $null }
        previous_rank = if ($prev) { [int]$prev.rank } else { $null }
        rank_delta = if ($cur -and $prev) { [int]$prev.rank - [int]$cur.rank } else { $null }
    }
}

$rows | Sort-Object -Property current_rank | Format-Table -AutoSize
