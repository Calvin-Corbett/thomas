param(
  [string]$Root = "",
  [switch]$AutoInstallTools
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Root)) {
  $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$bridgeRoot = Join-Path $Root "thomas\integrations\discord_bridge_service"
$packageJson = Join-Path $bridgeRoot "package.json"
$packageLock = Join-Path $bridgeRoot "package-lock.json"
$nodeMarker = Join-Path $bridgeRoot "node_modules\discord.js\package.json"

if (-not (Test-Path $packageJson)) {
  exit 0
}

function Get-CommandPathAny {
  param([string[]]$Names)
  foreach ($n in $Names) {
    $cmd = Get-Command $n -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
      return [string]$cmd.Source
    }
  }
  return ""
}

$node = Get-CommandPathAny @("node", "node.exe")
$npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
if (-not ($node -and $npm)) {
  Write-Host "[thomas] Discord bridge dependency sync skipped: Node.js and npm must already be installed."
  exit 0
}

if (-not (Test-Path $packageLock)) {
  throw "[thomas] Managed Discord bridge dependencies require package-lock.json. Regenerate the lockfile before continuing."
}

$bridgeDepsCurrent = $false
if (Test-Path $nodeMarker) {
  if ((Get-Item $nodeMarker).LastWriteTimeUtc -ge (Get-Item $packageLock).LastWriteTimeUtc) {
    $bridgeDepsCurrent = $true
  }
}

if ($bridgeDepsCurrent) {
  exit 0
}

Write-Host "[thomas] Installing embedded Discord bridge dependencies with npm ci..."
Push-Location $bridgeRoot
try {
  & $npm ci --no-audit --no-fund
  if ($LASTEXITCODE -ne 0) {
    throw "[thomas] Embedded Discord bridge dependency install failed (exit $LASTEXITCODE)."
  }
} finally {
  Pop-Location
}
