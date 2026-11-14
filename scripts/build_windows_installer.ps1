param(
  # Defaults to the version in pyproject.toml, the same one package_release.py stamps
  # into the bundle.
  [string]$Version = "",
  [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$VersionPattern = '(?m)^version\s*=\s*"([^"]+)"'
if ([string]::IsNullOrWhiteSpace($Version)) {
  $pyproject = [System.IO.File]::ReadAllText((Join-Path $Root "pyproject.toml"))
  $versionMatch = [regex]::Match($pyproject, $VersionPattern)
  if (-not $versionMatch.Success) {
    throw "[thomas] could not read the version from pyproject.toml; pass -Version"
  }
  $Version = $versionMatch.Groups[1].Value
}

$DistDir = Join-Path $Root "dist\installer"
$BundleName = "Thomas_source_{0}" -f $Version
$StageDir = Join-Path $DistDir $BundleName
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

function Get-IsccPath {
  $candidates = @()
  if ($env:ISCC_PATH) { $candidates += $env:ISCC_PATH }
  $candidates += @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
  )
  foreach ($path in $candidates) {
    if ([string]::IsNullOrWhiteSpace($path)) { continue }
    if (Test-Path $path) { return $path }
  }
  return ""
}

function Get-PythonCommand {
  $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) { return @($venvPython) }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return @($python.Source) }
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) { return @($launcher.Source, "-3") }
  return @()
}

function Remove-Stage {
  Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
}

# The installer carries the release bundle, never the working tree. The working tree holds
# this machine's .venv, runtime state, .env.local and untracked files. package_release.py
# selects tracked files from an allow-list, and the same bundle becomes the source zip.
$python = @(Get-PythonCommand)
if ($python.Count -eq 0) {
  throw "[thomas] Python 3 is needed to stage the release bundle (scripts\package_release.py). Install Python or create .venv."
}

if (Get-Command git -ErrorAction SilentlyContinue) {
  $dirty = & git status --porcelain --untracked-files=no
  if ($dirty) {
    Write-Warning "[thomas] Tracked files have uncommitted changes and will be in this installer. Commit first to ship exactly what git holds."
  }
}

Write-Host ("[thomas] Staging the release bundle for version {0}..." -f $Version)
$stageArgs = @($python | Select-Object -Skip 1) + @(
  "scripts\package_release.py",
  "--version", $Version,
  "--out-dir", "dist\installer",
  "--name", $BundleName
)
& $python[0] @stageArgs
if ($LASTEXITCODE -ne 0) {
  throw "[thomas] release bundle staging failed (exit $LASTEXITCODE)"
}

# The shortcuts in ThomasSetup.iss and the first launch need these. Fail here rather than
# hand out an installer that cannot start.
$required = @(
  "launch-thomas.vbs", "run-ui.cmd", "repair.cmd", "pyproject.toml", "thomas.toml", "README.md",
  "assets\thomas.ico", "scripts\run-ui.ps1", "scripts\repair.ps1", "scripts\setup.ps1",
  "scripts\startup_recovery_watch.ps1"
)
foreach ($relative in $required) {
  if (-not (Test-Path -LiteralPath (Join-Path $StageDir $relative))) {
    throw ("[thomas] the release bundle is missing {0}; check the allow-list in scripts\package_release.py" -f $relative)
  }
}

# RELEASE_MANIFEST.json travels with the installer and the source zip. It must not name
# the folder this machine built in.
$manifestText = [System.IO.File]::ReadAllText((Join-Path $StageDir "RELEASE_MANIFEST.json"))
foreach ($buildPath in @($Root, $Root.Replace("\", "\\"), $Root.Replace("\", "/"))) {
  if ($manifestText.IndexOf($buildPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
    throw "[thomas] RELEASE_MANIFEST.json names this machine's build folder; fix scripts\package_release.py before shipping"
  }
}
Write-Host ("[thomas] Source bundle: {0}" -f (Join-Path $DistDir ($BundleName + ".zip")))

if ($SkipCompile) {
  Write-Host "[thomas] Skipping Inno Setup compile (-SkipCompile)."
  Remove-Stage
  exit 0
}

$iscc = Get-IsccPath
if (-not $iscc) {
  Write-Host "[thomas] ISCC.exe not found. Set ISCC_PATH or install Inno Setup 6.3 or newer."
  Write-Host "[thomas] Download: https://jrsoftware.org/isinfo.php"
  Remove-Stage
  exit 2
}

$iss = Join-Path $Root "installer\ThomasSetup.iss"
if (-not (Test-Path $iss)) {
  throw "[thomas] Missing Inno Setup script: $iss"
}

Write-Host ("[thomas] Compiling installer with Inno Setup: {0}" -f $iscc)
& $iscc "/DMyAppVersion=$Version" "/DStageDir=$StageDir" $iss
if ($LASTEXITCODE -ne 0) {
  throw "[thomas] ISCC compile failed (exit $LASTEXITCODE); the staged bundle is kept at $StageDir"
}
Remove-Stage

Write-Host ("[thomas] Installer output directory: {0}" -f $DistDir)
