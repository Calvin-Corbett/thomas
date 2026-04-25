param(
  [Parameter(Mandatory = $true)]
  [string]$SetupExe,
  [Parameter(Mandatory = $true)]
  [string]$InstallDir,
  [string]$InstallLog = "",
  [string]$UninstallLog = "",
  [switch]$RequireBundledWheelhouse,
  [switch]$SkipFirstRun
)

$ErrorActionPreference = "Stop"

function Assert-SafeTempPath {
  param([Parameter(Mandatory = $true)][string]$Path)

  $full = [System.IO.Path]::GetFullPath($Path)
  $allowedRoots = @()
  if (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    $allowedRoots += [System.IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd("\")
  }
  if (-not [string]::IsNullOrWhiteSpace($env:TEMP)) {
    $allowedRoots += [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd("\")
  }
  if (-not [string]::IsNullOrWhiteSpace($env:TMP)) {
    $allowedRoots += [System.IO.Path]::GetFullPath($env:TMP).TrimEnd("\")
  }

  foreach ($root in ($allowedRoots | Select-Object -Unique)) {
    if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
      return
    }
  }

  throw "Refusing to clean install path outside TEMP/RUNNER_TEMP: $full"
}

function Assert-InstalledFile {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  $path = Join-Path $Root $RelativePath
  if (-not (Test-Path $path -PathType Leaf)) {
    throw "Expected installed file is missing: $RelativePath"
  }
}

$SetupExe = [System.IO.Path]::GetFullPath($SetupExe)
if (-not (Test-Path $SetupExe -PathType Leaf)) {
  throw "Installer was not found: $SetupExe"
}

Assert-SafeTempPath -Path $InstallDir
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
if ([string]::IsNullOrWhiteSpace($InstallLog)) {
  $InstallLog = Join-Path ([System.IO.Path]::GetDirectoryName($InstallDir)) "thomas-installer-smoke-install.log"
}
if ([string]::IsNullOrWhiteSpace($UninstallLog)) {
  $UninstallLog = Join-Path ([System.IO.Path]::GetDirectoryName($InstallDir)) "thomas-installer-smoke-uninstall.log"
}

Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
Remove-Item -Force $InstallLog,$UninstallLog -ErrorAction SilentlyContinue

try {
  $install = Start-Process -FilePath $SetupExe -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=$InstallDir",
    "/LOG=$InstallLog"
  ) -Wait -PassThru
  if ($install.ExitCode -ne 0) {
    if (Test-Path $InstallLog) {
      Get-Content -Tail 200 $InstallLog | Write-Host
    }
    throw "Installer exited with code $($install.ExitCode). Log: $InstallLog"
  }

  foreach ($relativePath in @(
    "launch-thomas.vbs",
    "support.cmd",
    "installer\wheelhouse\WHEELHOUSE_MANIFEST.json",
    "scripts\first-run.cmd",
    "scripts\first_run_wizard.ps1",
    "scripts\run-ui.ps1"
  )) {
    Assert-InstalledFile -Root $InstallDir -RelativePath $relativePath
  }

  if (-not $SkipFirstRun) {
    $wizard = Join-Path $InstallDir "scripts\first_run_wizard.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $wizard -ConfirmedInstallChanges -NoPrompt -NoLaunch -NoBrowser
    if ($LASTEXITCODE -ne 0) {
      throw "First-run wizard exited with code $LASTEXITCODE"
    }

    foreach ($relativePath in @(
      ".venv\Scripts\python.exe",
      "runtime\setup\dependency_install_source.txt",
      "runtime\setup\last_setup.txt",
      "runtime\logs\first_run_wizard.log"
    )) {
      Assert-InstalledFile -Root $InstallDir -RelativePath $relativePath
    }

    if ($RequireBundledWheelhouse) {
      $installSource = (Get-Content (Join-Path $InstallDir "runtime\setup\dependency_install_source.txt") -Raw).Trim()
      if ($installSource -ne "bundled-wheelhouse") {
        throw "Expected dependency install source to be bundled-wheelhouse, got: $installSource"
      }
    }
  }

  Write-Host ("Installer smoke passed: {0}" -f $SetupExe)
} finally {
  $uninstaller = Join-Path $InstallDir "unins000.exe"
  if (Test-Path $uninstaller) {
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @(
      "/VERYSILENT",
      "/SUPPRESSMSGBOXES",
      "/NORESTART",
      "/LOG=$UninstallLog"
    ) -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) {
      Write-Warning "Uninstaller exited with code $($uninstall.ExitCode). Log: $UninstallLog"
    }
  }
  Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
}
