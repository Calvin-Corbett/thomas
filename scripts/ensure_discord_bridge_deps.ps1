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

function Test-WingetAvailable {
  $winget = Get-CommandPathAny @("winget", "winget.exe")
  return -not [string]::IsNullOrWhiteSpace($winget)
}

function Install-WithWinget {
  param(
    [Parameter(Mandatory = $true)][string]$PackageId,
    [Parameter(Mandatory = $true)][string]$DisplayName
  )

  if (-not (Test-WingetAvailable)) {
    Write-Host ("[thomas] winget not found. Cannot auto-install {0}." -f $DisplayName)
    return $false
  }

  $wingetExe = Get-CommandPathAny @("winget", "winget.exe")
  Write-Host ("[thomas] Installing {0} via winget..." -f $DisplayName)
  & $wingetExe install --id $PackageId --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
  return ($LASTEXITCODE -eq 0)
}

function Ensure-NodeAndNpmInstalled {
  $node = Get-CommandPathAny @("node", "node.exe")
  $npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
  if ($node -and $npm) {
    return @{ Node = $node; Npm = $npm }
  }

  if (-not $AutoInstallTools) {
    Write-Host "[thomas] Discord bridge dependencies skipped: Node.js or npm is not installed."
    return $null
  }

  if (-not (Install-WithWinget -PackageId "OpenJS.NodeJS.LTS" -DisplayName "Node.js LTS")) {
    Write-Host "[thomas] Discord bridge dependencies skipped: Node.js install did not complete."
    return $null
  }

  $node = Get-CommandPathAny @("node", "node.exe")
  $npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
  if ($node -and $npm) {
    return @{ Node = $node; Npm = $npm }
  }

  Write-Host "[thomas] Discord bridge dependencies skipped: Node.js was installed but npm is still unavailable in this shell."
  return $null
}

$bridgeDepsCurrent = $false
if (Test-Path $nodeMarker) {
  if (-not (Test-Path $packageLock)) {
    $bridgeDepsCurrent = $true
  } elseif ((Get-Item $nodeMarker).LastWriteTimeUtc -ge (Get-Item $packageLock).LastWriteTimeUtc) {
    $bridgeDepsCurrent = $true
  }
}

if ($bridgeDepsCurrent) {
  exit 0
}

$tooling = Ensure-NodeAndNpmInstalled
if ($null -eq $tooling) {
  exit 0
}

$npm = [string]$tooling.Npm
$npmArgs = @()
if (Test-Path $packageLock) {
  $npmArgs = @("ci", "--no-audit", "--no-fund")
} else {
  $npmArgs = @("install", "--no-audit", "--no-fund")
}

Write-Host "[thomas] Installing embedded Discord bridge dependencies..."
Push-Location $bridgeRoot
try {
  & $npm @npmArgs
  if ($LASTEXITCODE -ne 0) {
    throw "[thomas] Embedded Discord bridge dependency install failed (exit $LASTEXITCODE)."
  }
} finally {
  Pop-Location
}
