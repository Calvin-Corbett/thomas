param(
  [string]$Version = "0.0.0-dev",
  [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

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

$robocopyArgs = @(
  $Root,
  $StageDir,
  "/E",
  "/XD", ".git", ".venv", "node_modules", "runtime", "dist", "pack", "output", "logs", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "nul",
  "/XF", "*.pyc", "*.pyo", "*.zip", "nul",
  "/R:2",
  "/W:2",
  "/NFL",
  "/NDL",
  "/NJH",
  "/NJS",
  "/NP"
)

& robocopy @robocopyArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -gt 7) {
  throw "[thomas] robocopy staging failed (exit $rc)"
}

$sourceZip = Join-Path $DistDir ("Thomas_source_{0}.zip" -f $Version)
if (Test-Path $sourceZip) {
  Remove-Item -Force $sourceZip
}
$zipItems = Get-ChildItem -Path $StageDir -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -ne "nul" } |
  Select-Object -ExpandProperty FullName
if (-not $zipItems -or $zipItems.Count -eq 0) {
  throw "[thomas] staging directory is empty after filtering; cannot create source bundle"
}
Compress-Archive -Path $zipItems -DestinationPath $sourceZip -CompressionLevel Optimal
Write-Host ("[thomas] Source bundle: {0}" -f $sourceZip)
try {
  Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
} catch {
  # non-blocking cleanup
}

if ($SkipCompile) {
  Write-Host "[thomas] Skipping Inno Setup compile (--SkipCompile)."
  exit 0
}

$iscc = Get-IsccPath
if (-not $iscc) {
  Write-Host "[thomas] ISCC.exe not found. Set ISCC_PATH or install Inno Setup 6."
  Write-Host "[thomas] Download: https://jrsoftware.org/isinfo.php"
  exit 2
}

$iss = Join-Path $Root "installer\ThomasSetup.iss"
if (-not (Test-Path $iss)) {
  throw "[thomas] Missing Inno Setup script: $iss"
}

Write-Host ("[thomas] Compiling installer with Inno Setup: {0}" -f $iscc)
& $iscc "/DMyAppVersion=$Version" $iss
if ($LASTEXITCODE -ne 0) {
  throw "[thomas] ISCC compile failed (exit $LASTEXITCODE)"
}

Write-Host ("[thomas] Installer output directory: {0}" -f $DistDir)
