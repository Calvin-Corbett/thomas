<#
.SYNOPSIS
  Launch the Thomas worker agent inside a network-isolated Windows Sandbox.

.DESCRIPTION
  Cage PROBLEM 1 (containment). Generates a .wsb config via
  scripts/cage/build_sandbox_config.py and launches Windows Sandbox with it.
  The box has NO network (so it cannot clone to a remote or exfil), maps ONLY
  the repo + the cage inbox/outbox (so it cannot reach other repos or escape),
  and is disposable (changes outside the mapped read-write folders evaporate
  when it closes).

  The cage inbox/outbox are mapped folders, so the sandboxed worker submits via
  the commit-master inbox and the HOST-side commit-master (run as you, outside
  the box) does the signing + push. No network is needed for that handoff.

  This launcher is non-destructive and needs no admin. Two things DO need
  Calvin's one-time elevated action (flagged below and in docs/CAGE_SETUP.md):
    1. Enable the Windows Sandbox optional feature (+ reboot).
    2. Provision the host ACLs (scripts/cage/provision_cage.ps1).

.PARAMETER CageRoot
  Host cage channel root. Default: C:\ProgramData\ThomasCage.

.PARAMETER EnableNetwork
  DANGER: leave networking ON in the box (defeats clone/exfil containment).

.PARAMETER ConfigOnly
  Generate the .wsb and print its path, but do not launch.

.EXAMPLE
  .\scripts\cage\launch_sandbox.ps1
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [switch]$EnableNetwork,
    [switch]$ConfigOnly
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}

Write-Host "== Thomas cage: Windows Sandbox launcher ==" -ForegroundColor Cyan
Write-Host "  Repo: $RepoRoot"
Write-Host "  Cage: $CageRoot"

# --- feature check (Calvin elevated step #1 if missing) --------------------- #
$wsb = Join-Path $env:WINDIR "System32\WindowsSandbox.exe"
if (-not (Test-Path $wsb)) {
    Write-Warning "Windows Sandbox is not installed (WindowsSandbox.exe not found)."
    Write-Host @"

>> CALVIN, ELEVATED, ONE-TIME (then reboot):
     Enable-WindowsOptionalFeature -Online -FeatureName 'Containers-DisposableClientVM' -All

   Requires Windows 11 Pro/Enterprise + virtualization enabled in BIOS.
   After the reboot, re-run this launcher (no admin needed).
"@ -ForegroundColor Yellow
    if (-not $ConfigOnly) { exit 2 }
}

# --- ensure the host cage channels exist ------------------------------------ #
foreach ($d in @($CageRoot, (Join-Path $CageRoot "inbox"), (Join-Path $CageRoot "outbox"))) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# --- generate the .wsb ------------------------------------------------------ #
$runtimeDir = Join-Path $RepoRoot "runtime\cage"
if (-not (Test-Path $runtimeDir)) { New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null }
$wsbPath = Join-Path $runtimeDir "thomas_agent.wsb"

$python = "python"
$genArgs = @(
    (Join-Path $RepoRoot "scripts\cage\build_sandbox_config.py"),
    "--repo", $RepoRoot,
    "--cage-root", $CageRoot,
    "--out", $wsbPath
)
if ($EnableNetwork) { $genArgs += "--enable-network" }

& $python @genArgs
if ($LASTEXITCODE -ne 0) { throw "Failed to generate sandbox config." }

if ($EnableNetwork) {
    Write-Warning "Networking is ENABLED in this box. It CAN clone/push/exfil. Use only when you mean it."
}

if ($ConfigOnly) {
    Write-Host "Config written: $wsbPath (not launching; -ConfigOnly)." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $wsb)) {
    Write-Warning "Config generated at $wsbPath but Windows Sandbox is unavailable to launch it."
    exit 2
}

Write-Host "Launching Windows Sandbox..." -ForegroundColor Green
& $wsb $wsbPath
