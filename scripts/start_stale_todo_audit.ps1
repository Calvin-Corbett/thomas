$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$bgDir = Join-Path $repoRoot ".codex\background"
$pidPath = Join-Path $bgDir "stale_todo_audit.pid"
$stdoutPath = Join-Path $bgDir "stale_todo_audit.stdout.log"
$stderrPath = Join-Path $bgDir "stale_todo_audit.stderr.log"

New-Item -ItemType Directory -Force -Path $bgDir | Out-Null

$existing = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match '^python(?:\.exe)?$' -and
    $_.CommandLine -like '*scripts/watch_stale_todos.py*'
  } |
  Select-Object -First 1

if ($existing) {
  Set-Content -LiteralPath $pidPath -Value ([string]$existing.ProcessId) -Encoding ascii
  Write-Output ("already-running {0}" -f $existing.ProcessId)
  exit 0
}

$proc = Start-Process `
  -FilePath "python" `
  -ArgumentList @("scripts/watch_stale_todos.py", "--repo-root", ".", "--interval-seconds", "900", "--stale-days", "45") `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutPath `
  -RedirectStandardError $stderrPath `
  -PassThru

Set-Content -LiteralPath $pidPath -Value ([string]$proc.Id) -Encoding ascii
Write-Output ("started {0}" -f $proc.Id)
