Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$repoRoot = Get-ThomasRepoRoot
$result = Read-LatestSuiteResult -RepoRoot $repoRoot
$scope = $result.prediction_evo_scope

Write-Output "Predicted Next Competitor Focus:"
$focusRows = @($scope.aggregate_predicted_focus)
if ($focusRows) {
    $focusRows | Select-Object area, count | Format-Table -AutoSize
} else {
    Write-Output "- none"
}

Write-Output ""
Write-Output "Recommended Thomas Counter-Moves:"
$moves = @($scope.aggregate_recommended_counter_moves)
if ($moves) {
    $moves | Select-Object move, count | Format-Table -AutoSize -Wrap
} else {
    Write-Output "- none"
}
