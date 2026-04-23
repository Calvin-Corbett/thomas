$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $repoRoot ".codex\background\stale_todo_audit.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
  Write-Output "not-running"
  exit 0
}

$pidText = (Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
$pid = 0
[void][int]::TryParse(($pidText | Out-String).Trim(), [ref]$pid)

if ($pid -gt 0) {
  $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
  if ($proc) {
    Stop-Process -Id $pid -Force
    Write-Output ("stopped {0}" -f $pid)
  } else {
    Write-Output ("stale-pid {0}" -f $pid)
  }
} else {
  Write-Output "invalid-pid"
}

Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
