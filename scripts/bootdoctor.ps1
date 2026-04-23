param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$BootDoctorArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Find-SystemPython {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "python"; Path = $cmd.Source } }
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "py"; Path = $cmd.Source } }
  return $null
}

$VenvPy = Join-Path $RepoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $VenvPy)) {
  $sysPy = Find-SystemPython
  if (-not $sysPy) {
    Write-Host "[bootdoctor] ERROR: Python not found."
    exit 2
  }
  Write-Host "[bootdoctor] Creating .venv..."
  if ($sysPy.Kind -eq "py") {
    & $sysPy.Path -3 -m venv .venv
  } else {
    & $sysPy.Path -m venv .venv
  }
}

if (-not (Test-Path $VenvPy)) {
  Write-Host "[bootdoctor] ERROR: missing .venv\\Scripts\\python.exe"
  exit 2
}

$args = @("-m", "thomas.bootdoctor")
if ($BootDoctorArgs) { $args += $BootDoctorArgs }

& $VenvPy @args
exit $LASTEXITCODE
