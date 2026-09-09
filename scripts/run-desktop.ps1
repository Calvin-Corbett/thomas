param(
  [int]$Port = 8899,
  [switch]$NoInstall,
  [switch]$Spike
)

# Launch the Thomas desktop app -- the real browser shell.
#
# This is the sibling of run-ui.ps1. That one starts the server and hands the
# UI to whatever browser you have; this one starts Thomas as its own windowed
# application, where tabs are real web views and the agent can see and drive
# them. The app attaches to a server already listening on -Port, and starts
# one itself if nothing answers.

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Desktop = Join-Path $Root "desktop"
Set-Location $Root

$ElectronExe = Join-Path $Desktop "node_modules\electron\dist\electron.exe"

if (-not (Test-Path (Join-Path $Desktop "package.json"))) {
  Write-Host "[thomas] ERROR: desktop/ is missing from this checkout."
  exit 2
}

if (-not (Test-Path $ElectronExe) -and -not $NoInstall) {
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npm) {
    Write-Host "[thomas] ERROR: Node/npm not found, and desktop dependencies are not installed."
    Write-Host "[thomas] Install Node 20+ from https://nodejs.org and re-run."
    exit 2
  }
  Write-Host "[thomas] Installing desktop dependencies (first run only)..."
  Push-Location $Desktop
  try {
    & npm install --no-audit --no-fund
  } finally {
    Pop-Location
  }
}

if (-not (Test-Path $ElectronExe)) {
  # The npm optional-dependency bug can leave the package installed with no
  # binary. Say exactly that instead of failing with a confusing stack.
  Write-Host "[thomas] ERROR: Electron is installed but its binary is missing."
  Write-Host "[thomas] Fix: delete desktop\node_modules and desktop\package-lock.json, then re-run."
  exit 2
}

if ($Spike) {
  # The Phase 1 gauntlet: seven gates that must pass on every Electron bump.
  Write-Host "[thomas] Running the desktop gauntlet..."
  & $ElectronExe (Join-Path $Desktop "spike.js") --gates
  & $ElectronExe (Join-Path $Desktop "spike.js") --verify-persist
  Write-Host "[thomas] Results: desktop\spike-results.json"
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[thomas] Starting Thomas desktop (server port $Port)"
Write-Host "[thomas] Profile: runtime\browser_profile"
Write-Host ""

& $ElectronExe $Desktop --server-port $Port
exit $LASTEXITCODE
