param(
  [switch]$SkipInstall,
  [switch]$SkipDoctor,
  [switch]$AutoInstallTools,
  [switch]$NoAutoInstallTools,
  # No one to ask: every question is answered "no", except the winget tool install, which the
  # in-app Auto Repair button has always done (-NoAutoInstallTools turns that off too).
  # A caller whose console nobody can see MUST pass this: without it Read-Host waits for typing that cannot happen,
  # because this script does not try to tell that its console is hidden, and it never times a question out.
  [switch]$NoPrompt,
  [switch]$QuarantineCorrupt
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "[thomas] Repair starting..."
Write-Host ("[thomas] Root: {0}" -f $Root)
Write-Host "[thomas] Repair tests your config and databases, reinstalls dependencies, then runs doctor."

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$lines = @()

function Read-Consent {
  param([Parameter(Mandatory = $true)][string]$Question)
  if ($NoPrompt) { return $false }
  try {
    $answer = Read-Host ("{0} [y/N]" -f $Question)
  } catch {
    # No console to ask at (a hidden or non-interactive host): that is a no, and the repair carries on.
    Write-Host "[thomas] No answer was possible here, so the answer is no."
    return $false
  }
  return ($answer -match '^\s*(y|yes)\s*$')
}

function Invoke-VenvPython {
  # Native stderr must not abort the script (Stop turns each stderr line into an error).
  param([Parameter(Mandatory = $true)][string[]]$PyArgs)
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = & $venvPy @PyArgs 2>&1
    $code = [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
  $text = @()
  if ($out) { $text = @($out | ForEach-Object { [string]$_ }) }
  return [pscustomobject]@{ Exit = $code; Lines = $text }
}

# Exit codes come from `python -m thomas.bootdoctor check`: 0 fine, 1 a problem
# only you can fix (a config file that will not parse), 3 a damaged database.
$script:DataExit = 0

function Invoke-DataCheck {
  if (-not (Test-Path $venvPy)) {
    $script:lines += "data_check=skipped (.venv python not found)"
    return
  }
  Write-Host "[thomas] Testing your config, data folders and databases..."
  $run = Invoke-VenvPython @("-m", "thomas.bootdoctor", "check", "--root", $Root)
  $run.Lines | ForEach-Object { Write-Host ("[thomas]   {0}" -f $_) }
  $script:lines += "----- data check -----"
  $script:lines += $run.Lines
  $unresolved = $run.Lines
  if ($run.Exit -eq 3) {
    $move = $QuarantineCorrupt -or (Read-Consent "A database file is damaged. Move it aside (renamed, never deleted) so Thomas can start fresh?")
    if ($move) {
      $run = Invoke-VenvPython @("-m", "thomas.bootdoctor", "check", "--root", $Root, "--quarantine")
      if ($run.Exit -eq 2) {
        # check refuses to move files while Thomas is running, and words that as --force, which repair has no use for.
        Write-Host "[thomas] Thomas is running, so nothing was moved. Close Thomas, then run repair.cmd again."
        $script:lines += "data_check=quarantine refused because Thomas is running"
        $script:DataExit = 2
        return
      }
      # The move run repeats the first block, then reports the move and a second check.
      $from = [array]::IndexOf($run.Lines, "[bootdoctor] moving damaged database file(s) aside (renamed, not deleted):")
      if ($from -lt 0) { $from = 0 }
      $after = @($run.Lines | Select-Object -Skip $from)
      $after | ForEach-Object { Write-Host ("[thomas]   {0}" -f $_) }
      $script:lines += $after
      $again = [array]::IndexOf($after, "[bootdoctor] checked again after the move:")
      $unresolved = if ($again -ge 0) { @($after | Select-Object -Skip ($again + 1)) } else { $after }
    } else {
      Write-Host "[thomas] Left the damaged file where it is. Run repair.cmd again with -QuarantineCorrupt to move it aside."
    }
  }
  $script:lines += ""
  $unresolved | Where-Object { $_ -match '^\[fail\]' } | ForEach-Object { Write-Host ("[thomas] Needs your attention: {0}" -f $_) }
  $script:DataExit = $run.Exit
}

# Installing tools changes this machine, so a console run asks first. -NoPrompt callers
# (the in-app Auto Repair button) already asked by being pressed and keep the old default.
# -NoAutoInstallTools wins over every other switch. (-SkipInstall does not come into it: setup.ps1
# uses it only for the pip step, and still installs tools when it is handed -AutoInstallTools.)
function Resolve-InstallTools {
  param([bool]$Never, [bool]$Always, [bool]$Unattended)
  if ($Never) { return $false }
  if ($Always -or $Unattended) { return $true }
  return (Read-Consent "Repair can install missing tools (Python, Node.js, Ollama, Codex) with winget. Allow this?")
}

$installTools = Resolve-InstallTools -Never ([bool]$NoAutoInstallTools) -Always ([bool]$AutoInstallTools) -Unattended ([bool]$NoPrompt)

# The repair ends "ok" (exit 0) only when setup, the data check and, unless it was skipped, doctor all exited 0. The
# exit codes are left untyped on purpose: a setup exit that never got a value is not 0, and must not become one.
function Test-RepairOk {
  param($SetupExit, $DataExit, $DoctorExit, [bool]$SkipDoctor)
  return ($SetupExit -eq 0 -and $DataExit -eq 0 -and ($SkipDoctor -or $DoctorExit -eq 0))
}

$setupScript = Join-Path $Root "scripts\setup.ps1"
if (-not (Test-Path $setupScript)) {
  Write-Host ("[thomas] ERROR: setup script not found: {0}" -f $setupScript)
  exit 2
}

$setupArgs = @("-Easy", "-NoPrompt")
if ($installTools) {
  $setupArgs += "-AutoInstallTools"
}
if ($SkipInstall) {
  $setupArgs += "-SkipInstall"
}
$setupArgs += "-SkipDoctor"

& powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript @setupArgs
$setupExit = $LASTEXITCODE

# After setup, not before: the check imports Thomas, which needs the dependencies setup
# just repaired, and a first run has no venv until setup creates it. Setup's exit code is
# only read here, so a failing setup does not stop the check.
Invoke-DataCheck

$setupDir = Join-Path $Root "runtime\setup"
New-Item -ItemType Directory -Force -Path $setupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportPath = Join-Path $setupDir ("repair_{0}.txt" -f $stamp)

$report = @()
$report += ("timestamp={0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$report += ("setup_exit={0}" -f $setupExit)
$report += ("install_tools={0}" -f $installTools)
$report += ("data_check_exit={0}" -f $script:DataExit)
$report += $script:lines

$doctorExit = 0
if (-not $SkipDoctor) {
  if (Test-Path $venvPy) {
    $report += "doctor_mode=full"
    $report += ""
    $report += "----- doctor --full output -----"
    try {
      $doctor = Invoke-VenvPython @("-m", "thomas", "doctor", "--full")
      $report += $doctor.Lines
      $doctorExit = $doctor.Exit
    } catch {
      $doctorExit = 1
      $report += ("doctor_error={0}" -f $_.Exception.Message)
    }
  } else {
    $doctorExit = 1
    $report += "doctor_error=.venv python not found"
  }
} else {
  $report += "doctor_mode=skipped"
}

$report += ""
$report += ("doctor_exit={0}" -f $doctorExit)
$ok = Test-RepairOk -SetupExit $setupExit -DataExit $script:DataExit -DoctorExit $doctorExit -SkipDoctor ([bool]$SkipDoctor)
$report += ("ok={0}" -f $ok)

Set-Content -Path $reportPath -Encoding UTF8 -Value $report

Write-Host ("[thomas] Repair report: {0}" -f $reportPath)
if ($ok) {
  Write-Host "[thomas] Repair completed successfully."
  exit 0
}

Write-Host "[thomas] Repair completed with issues."
exit 1
