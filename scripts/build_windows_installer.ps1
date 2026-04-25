param(
  [string]$Version = "0.0.0-dev",
  [switch]$SkipCompile,
  [switch]$SkipWheelhouse
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Get-ProjectVersion {
  $pyproject = Join-Path $Root "pyproject.toml"
  if (-not (Test-Path $pyproject)) { return "" }
  $match = Select-String -Path $pyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
  if (-not $match) { return "" }
  return [string]$match.Matches[0].Groups[1].Value
}

if ($Version -eq "0.0.0-dev") {
  $projectVersion = Get-ProjectVersion
  if ($projectVersion) {
    $Version = $projectVersion
  }
}

$DistDir = Join-Path $Root "dist\installer"
$StageDir = Join-Path $DistDir ("staging_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

function Get-IsccPath {
  $candidates = @()
  if ($env:ISCC_PATH) { $candidates += $env:ISCC_PATH }
  $candidates += @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
  )
  foreach ($path in $candidates) {
    if ([string]::IsNullOrWhiteSpace($path)) { continue }
    if (Test-Path $path) { return $path }
  }
  return ""
}

Write-Host "[thomas] Preparing installer staging directory..."
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$trackedFiles = & git ls-files
if ($LASTEXITCODE -ne 0 -or -not $trackedFiles) {
  throw "[thomas] git ls-files failed; installer builds require a git checkout."
}

foreach ($rel in $trackedFiles) {
  if ([string]::IsNullOrWhiteSpace($rel)) { continue }
  $src = Join-Path $Root $rel
  if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }
  $dest = Join-Path $StageDir $rel
  $destDir = Split-Path -Parent $dest
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null
  Copy-Item -LiteralPath $src -Destination $dest -Force
}

$sourceZip = Join-Path $DistDir ("Thomas_source_{0}.zip" -f $Version)
if (Test-Path $sourceZip) {
  Remove-Item -Force $sourceZip
}
$zipItems = Get-ChildItem -Path $StageDir -Recurse -File -Force -ErrorAction SilentlyContinue
if (-not $zipItems -or $zipItems.Count -eq 0) {
  throw "[thomas] staging directory is empty after filtering; cannot create source bundle"
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($StageDir, $sourceZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
Write-Host ("[thomas] Source bundle: {0}" -f $sourceZip)

if (-not $SkipWheelhouse) {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python -or -not $python.Source) {
    throw "[thomas] python was not found; installer wheelhouse builds require Python."
  }

  $wheelhouseDir = Join-Path $StageDir "installer\wheelhouse"
  Write-Host ("[thomas] Building offline installer wheelhouse: {0}" -f $wheelhouseDir)
  & $python.Source "scripts\build_installer_wheelhouse.py" --dest $wheelhouseDir
  if ($LASTEXITCODE -ne 0) {
    throw "[thomas] installer wheelhouse build failed (exit $LASTEXITCODE)"
  }
  if (-not (Test-Path (Join-Path $wheelhouseDir "WHEELHOUSE_MANIFEST.json") -PathType Leaf)) {
    throw "[thomas] installer wheelhouse manifest was not produced."
  }
} else {
  Write-Host "[thomas] Skipping offline installer wheelhouse build (--SkipWheelhouse)."
}

if ($SkipCompile) {
  try {
    Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
  } catch {
    # non-blocking cleanup
  }
  Write-Host "[thomas] Skipping Inno Setup compile (--SkipCompile)."
  exit 0
}

$iscc = Get-IsccPath
if (-not $iscc) {
  Write-Host "[thomas] ISCC.exe not found. Set ISCC_PATH or install Inno Setup 6."
  Write-Host "[thomas] Download: https://jrsoftware.org/isinfo.php"
  exit 2
}

$iss = Join-Path $StageDir "installer\ThomasSetup.iss"
if (-not (Test-Path $iss)) {
  throw "[thomas] Missing Inno Setup script: $iss"
}

Write-Host ("[thomas] Compiling installer with Inno Setup: {0}" -f $iscc)
& $iscc "/DMyAppVersion=$Version" $iss
if ($LASTEXITCODE -ne 0) {
  throw "[thomas] ISCC compile failed (exit $LASTEXITCODE)"
}

$stageExe = Join-Path $StageDir ("dist\installer\ThomasSetup_{0}.exe" -f $Version)
if (-not (Test-Path $stageExe)) {
  throw "[thomas] Expected installer was not produced: $stageExe"
}
Copy-Item -LiteralPath $stageExe -Destination $DistDir -Force
try {
  Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
} catch {
  # non-blocking cleanup
}

Write-Host ("[thomas] Installer output directory: {0}" -f $DistDir)
