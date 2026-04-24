[CmdletBinding()]
param(
  [switch]$NoLaunch,
  [switch]$NoBrowser,
  [switch]$ConfirmedInstallChanges,
  [switch]$NoPrompt,
  [int]$Port = 8899
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$LogDir = Join-Path $Root "runtime\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "first_run_wizard.log"

try {
  Start-Transcript -Path $LogPath -Append | Out-Null
} catch {
  Write-Host ("[thomas] NOTE: Could not start transcript: {0}" -f $_.Exception.Message)
}

function Stop-TranscriptIfRunning {
  try { Stop-Transcript | Out-Null } catch { }
}

function Write-Step {
  param([Parameter(Mandatory = $true)][string]$Message)
  Write-Host ""
  Write-Host ("[thomas] {0}" -f $Message)
}

function Confirm-Step {
  param(
    [Parameter(Mandatory = $true)][string]$Message,
    [switch]$DefaultYes
  )

  if ($ConfirmedInstallChanges) { return $true }
  if ($NoPrompt) { return $false }

  $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
  $answer = (Read-Host ("[thomas] {0} {1}" -f $Message, $suffix)).Trim().ToLowerInvariant()
  if ([string]::IsNullOrWhiteSpace($answer)) { return [bool]$DefaultYes }
  return ($answer -eq "y" -or $answer -eq "yes")
}

function Write-SupportInstructions {
  $supportDir = Join-Path $Root "runtime\support"
  Write-Host ""
  Write-Host "[thomas] What to try next:"
  Write-Host "[thomas] 1. Run repair.cmd from the Thomas install folder, then launch Thomas again."
  Write-Host "[thomas] 2. Run bootdoctor.cmd for startup diagnostics."
  Write-Host "[thomas] 3. Run support.cmd and attach the ZIP from runtime\support\ to a GitHub install issue."
  Write-Host ("[thomas] Support ZIP folder: {0}" -f $supportDir)
  Write-Host "[thomas] Install issue form: https://github.com/Calvin-Corbett/thomas/issues/new?template=install_failure.yml"
  Write-Host ("[thomas] Expected local browser URL after setup: http://127.0.0.1:{0}/" -f $Port)
}

function Fail-Setup {
  param([Parameter(Mandatory = $true)][string]$Message)
  Write-Host ""
  Write-Host ("[thomas] ERROR: {0}" -f $Message)
  Write-Host ("[thomas] Setup log: {0}" -f $LogPath)
  Write-SupportInstructions
  if (-not $NoPrompt) {
    Read-Host "[thomas] Press Enter to close"
  }
  Stop-TranscriptIfRunning
  exit 1
}

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Exe @Args 2>&1 | Out-Host
    return [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Get-CommandPathAny {
  param([Parameter(Mandatory = $true)][string[]]$Names)
  foreach ($name in $Names) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return [string]$cmd.Source }
  }
  return ""
}

function Find-SystemPython {
  $candidates = @()
  $python = Get-CommandPathAny @("python", "python.exe")
  if ($python) {
    $candidates += [pscustomobject]@{ Kind = "python"; Path = $python; PrefixArgs = @() }
  }
  $py = Get-CommandPathAny @("py", "py.exe")
  if ($py) {
    $candidates += [pscustomobject]@{ Kind = "py"; Path = $py; PrefixArgs = @("-3") }
  }

  $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
  if (Test-Path $localPrograms) {
    $direct = Get-ChildItem -Path $localPrograms -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending
    foreach ($item in $direct) {
      $candidates += [pscustomobject]@{ Kind = "python"; Path = $item.FullName; PrefixArgs = @() }
    }
  }

  foreach ($candidate in $candidates) {
    try {
      $args = @($candidate.PrefixArgs) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)")
      & $candidate.Path @args 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { return $candidate }
    } catch { }
  }

  return $null
}

function Install-PythonWithWinget {
  $winget = Get-CommandPathAny @("winget", "winget.exe")
  if (-not $winget) { return $false }

  Write-Step "Python 3.10+ was not found. Installing Python 3.12 with winget."
  $code = Invoke-Native $winget @(
    "install",
    "--id", "Python.Python.3.12",
    "--exact",
    "--silent",
    "--scope", "user",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  )
  return ($code -eq 0)
}

function Invoke-Python {
  param(
    [Parameter(Mandatory = $true)]$PythonSpec,
    [Parameter(Mandatory = $true)][string[]]$Args
  )
  $fullArgs = @($PythonSpec.PrefixArgs) + $Args
  return Invoke-Native $PythonSpec.Path $fullArgs
}

function Invoke-VenvPython {
  param([Parameter(Mandatory = $true)][string[]]$Args)
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  return Invoke-Native $venvPy $Args
}

function Assert-PathInsideRoot {
  param([Parameter(Mandatory = $true)][string]$Path)
  $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\")
  $targetFull = [System.IO.Path]::GetFullPath($Path)
  if (-not $targetFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail-Setup ("Refusing to modify path outside Thomas install directory: {0}" -f $targetFull)
  }
}

Write-Host "Thomas first-run setup"
Write-Host "This window will prepare the local runtime, then launch Thomas."
Write-Host ("Install folder: {0}" -f $Root)
Write-Host ("Setup log: {0}" -f $LogPath)

$pythonSpec = Find-SystemPython
if (-not $pythonSpec) {
  if (Confirm-Step "Install Python 3.12 automatically with winget?" -DefaultYes) {
    if (-not (Install-PythonWithWinget)) {
      Fail-Setup "Python install through winget failed or winget is not available. Install Python 3.10+ from https://www.python.org/downloads/windows/ and run Thomas again."
    }
    $pythonSpec = Find-SystemPython
  }
}

if (-not $pythonSpec) {
  Fail-Setup "Python 3.10+ was not found. Install Python from https://www.python.org/downloads/windows/ and run Thomas again."
}

Write-Step ("Using Python: {0}" -f $pythonSpec.Path)

$venvDir = Join-Path $Root ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if ((Test-Path $venvDir) -and -not (Test-Path $venvPy)) {
  Assert-PathInsideRoot $venvDir
  Write-Step "Existing .venv is incomplete. Recreating it."
  Remove-Item -Recurse -Force $venvDir
}

if (-not (Test-Path $venvPy)) {
  Write-Step "Creating Thomas local Python environment."
  $code = Invoke-Python $pythonSpec @("-m", "venv", ".venv")
  if ($code -ne 0 -or -not (Test-Path $venvPy)) {
    Fail-Setup "Could not create .venv."
  }
}

Write-Step "Installing Thomas dependencies. This can take several minutes on first install."
$code = Invoke-VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check")
if ($code -ne 0) { Fail-Setup "pip upgrade failed." }

$code = Invoke-VenvPython @("-m", "pip", "install", "-e", ".[server,repl]", "--disable-pip-version-check")
if ($code -ne 0) { Fail-Setup "Python dependency install failed." }

$code = Invoke-VenvPython @("-c", "import aiohttp, cryptography, httpx, prompt_toolkit; from PIL import Image")
if ($code -ne 0) { Fail-Setup "Dependency verification failed." }

$setupScript = Join-Path $Root "scripts\setup.ps1"
if (Test-Path $setupScript) {
  Write-Step "Writing default Thomas configuration."
  & powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript -Easy -NoPrompt -SkipInstall -SkipDoctor
  if ($LASTEXITCODE -ne 0) {
    Fail-Setup "Thomas setup script failed."
  }
}

Write-Step "First-run setup completed."

if (-not $NoLaunch) {
  Write-Step "Launching Thomas."
  $runScript = Join-Path $Root "scripts\run-ui.ps1"
  $runArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $runScript,
    "-ConfirmedInstallChanges",
    "-NoPrompt",
    "-NoTray",
    "-Port", "$Port"
  )
  if ($NoBrowser) { $runArgs += "-NoBrowser" }
  & powershell @runArgs
  if ($LASTEXITCODE -ne 0) {
    Fail-Setup "Thomas launch failed after setup."
  }
}

Write-Host ""
Write-Host "[thomas] Ready."
Write-Host ("[thomas] Setup log: {0}" -f $LogPath)

Stop-TranscriptIfRunning
exit 0
