param(
  [switch]$SkipInstall,
  [switch]$SkipDoctor,
  [switch]$NoAutoInstallTools,
  [switch]$ConfirmedToolInstall,
  [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "[thomas] Repair starting..."
Write-Host ("[thomas] Root: {0}" -f $Root)

$setupScript = Join-Path $Root "scripts\setup.ps1"
if (-not (Test-Path $setupScript)) {
  Write-Host ("[thomas] ERROR: setup script not found: {0}" -f $setupScript)
  exit 2
}

$setupArgs = @("-Easy", "-NoPrompt")
if (-not $NoAutoInstallTools) {
  $setupArgs += "-AutoInstallTools"
  if ($ConfirmedToolInstall) {
    $setupArgs += "-ConfirmedToolInstall"
  }
}
if ($SkipInstall) {
  $setupArgs += "-SkipInstall"
}
$setupArgs += "-SkipDoctor"

& powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript @setupArgs
$setupExit = $LASTEXITCODE

$setupDir = Join-Path $Root "runtime\setup"
New-Item -ItemType Directory -Force -Path $setupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportPath = Join-Path $setupDir ("repair_{0}.txt" -f $stamp)

$lines = @()
$lines += ("timestamp={0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$lines += ("setup_exit={0}" -f $setupExit)

$doctorExit = 0
if (-not $SkipDoctor) {
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) {
    $lines += "doctor_mode=full"
    $lines += ""
    $lines += "----- doctor --full output -----"
    try {
      $doctorOut = & $venvPy -m thomas doctor --full 2>&1
      if ($doctorOut) {
        $lines += ($doctorOut | ForEach-Object { [string]$_ })
      }
      $doctorExit = $LASTEXITCODE
    } catch {
      $doctorExit = 1
      $lines += ("doctor_error={0}" -f $_.Exception.Message)
    }
  } else {
    $doctorExit = 1
    $lines += "doctor_error=.venv python not found"
  }
} else {
  $lines += "doctor_mode=skipped"
}

$lines += ""
$lines += ("doctor_exit={0}" -f $doctorExit)
$ok = ($setupExit -eq 0 -and ($SkipDoctor -or $doctorExit -eq 0))
$lines += ("ok={0}" -f $ok)

Set-Content -Path $reportPath -Encoding UTF8 -Value $lines

Write-Host ("[thomas] Repair report: {0}" -f $reportPath)
if ($ok) {
  Write-Host "[thomas] Repair completed successfully."
  exit 0
}

Write-Host "[thomas] Repair completed with issues."
exit 1
