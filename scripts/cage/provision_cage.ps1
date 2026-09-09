<#
.SYNOPSIS
  Provision the Praxis "cage": a separate non-admin OS user for the Thomas
  worker agent, with the gate scripts, keys, .git internals, and the
  commit-master owned by you and read-only (or no-access) to the agent.

.DESCRIPTION
  This is Part 1 + Part 2 of the cage (see docs/CAGE_SETUP.md). It turns the
  "same-user-shell-controls-local-state" residual from the Praxis exercise
  into a real privilege boundary:

    * Part 1 - the worker agent runs as a dedicated NON-ADMIN local user
      ('thomas-agent' by default). That account cannot read your files, the
      signing key, or the gate-control state.

    * Part 2 - the safety-critical paths are owned by YOU and made read-only
      (gates, commit-master, agent_safety.toml) or NO-access (runtime HMAC key,
      breakglass audit log) to the agent account. The one-way cage channels
      (inbox/outbox) get the only cross-user permissions the agent needs.

  After this runs, the agent's ONLY way to affect the repo is to drop a
  submission into the inbox; the commit-master (run as YOU) is the only
  identity that can commit/sign/push.

  MUST be run from an elevated (Administrator) PowerShell. Creating a local
  user and setting cross-user ACLs both require admin.

.PARAMETER AgentUser
  Local account name for the worker agent. Default: 'thomas-agent'.

.PARAMETER OwnerUser
  The account that OWNS the safety-critical paths and runs the commit-master.
  Default: the current user ($env:USERNAME).

.PARAMETER RepoRoot
  Path to the Thomas repo. Default: the repo this script lives in.

.PARAMETER CageRoot
  Where the one-way channels live, OUTSIDE the worktree so the agent's repo
  access doesn't imply channel control. Default: C:\ProgramData\ThomasCage.

.PARAMETER WhatIf
  Print the actions without making changes.

.EXAMPLE
  # From an elevated PowerShell:
  .\scripts\cage\provision_cage.ps1 -AgentUser thomas-agent
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AgentUser = "thomas-agent",
    [string]$OwnerUser = $env:USERNAME,
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage"
)

$ErrorActionPreference = "Stop"

# Resolve RepoRoot in-body: $PSScriptRoot can be empty when evaluated inside a
# param default under some invocation styles, so fall back robustly.
if (-not $RepoRoot) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw "This script must be run from an elevated (Administrator) PowerShell."
    }
}

function Invoke-Icacls {
    param([string[]]$IcaclsArgs)
    if ($PSCmdlet.ShouldProcess(($IcaclsArgs -join ' '), 'icacls')) {
        & icacls @IcaclsArgs | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning ("icacls returned $LASTEXITCODE for: " + ($IcaclsArgs -join ' '))
        }
    }
}

Write-Host "== Thomas cage provisioning ==" -ForegroundColor Cyan
Write-Host "  Repo:   $RepoRoot"
Write-Host "  Owner:  $OwnerUser"
Write-Host "  Agent:  $AgentUser"
Write-Host "  Cage:   $CageRoot"
Assert-Admin

# --------------------------------------------------------------------------- #
# Part 1: the non-admin worker account
# --------------------------------------------------------------------------- #
Write-Host "`n[1/4] Worker account ($AgentUser, non-admin)..." -ForegroundColor Cyan
$existing = Get-LocalUser -Name $AgentUser -ErrorAction SilentlyContinue
if (-not $existing) {
    # Generate a random password the agent never needs (it runs via
    # 'runas /user' or a scheduled task; you store this in your own vault).
    Add-Type -AssemblyName System.Web
    $pw = [System.Web.Security.Membership]::GeneratePassword(24, 6)
    $secure = ConvertTo-SecureString $pw -AsPlainText -Force
    if ($PSCmdlet.ShouldProcess($AgentUser, 'New-LocalUser')) {
        # NB: New-LocalUser caps -Description at 48 chars; keep it short.
        New-LocalUser -Name $AgentUser -Password $secure -FullName "Thomas Worker Agent" `
            -Description "Thomas worker agent (non-admin, Praxis cage)" `
            -PasswordNeverExpires | Out-Null
        Write-Host "  Created $AgentUser." -ForegroundColor Green
        Write-Host "  >> One-time password (store in YOUR vault, not the repo):" -ForegroundColor Yellow
        Write-Host "     $pw" -ForegroundColor Yellow
    }
}
else {
    Write-Host "  $AgentUser already exists; leaving as-is." -ForegroundColor Green
}
# Ensure it is NOT an administrator.
$adminMembers = (Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
if ($adminMembers -match "\\$AgentUser$") {
    Write-Warning "  $AgentUser is in Administrators - removing (the agent must be non-admin)."
    if ($PSCmdlet.ShouldProcess($AgentUser, 'Remove-LocalGroupMember Administrators')) {
        Remove-LocalGroupMember -Group "Administrators" -Member $AgentUser
    }
}
else {
    Write-Host "  Confirmed $AgentUser is not an administrator." -ForegroundColor Green
}

# --------------------------------------------------------------------------- #
# Part 2a: lock the safety-critical paths (owner = you, read-only to agent)
# --------------------------------------------------------------------------- #
Write-Host "`n[2/4] Locking gate scripts / commit-master / config (read-only to agent)..." -ForegroundColor Cyan
# READ-ONLY to the agent: it may execute the gates and read config, but never
# edit them. Owner keeps full control.
$readOnlyPaths = @(
    (Join-Path $RepoRoot "scripts\forge\gates"),
    (Join-Path $RepoRoot "scripts\forge\commit_master.py"),
    (Join-Path $RepoRoot "scripts\commit_breakglass_guard.py"),
    (Join-Path $RepoRoot "scripts\cage"),
    (Join-Path $RepoRoot "agent_safety.toml"),
    (Join-Path $RepoRoot ".git\hooks"),
    (Join-Path $RepoRoot ".git\config")
)
foreach ($p in $readOnlyPaths) {
    if (-not (Test-Path $p)) { Write-Warning "  skip (missing): $p"; continue }
    Invoke-Icacls @($p, "/setowner", $OwnerUser, "/T", "/C")
    Invoke-Icacls @($p, "/inheritance:r")
    Invoke-Icacls @($p, "/grant:r", "${OwnerUser}:(OI)(CI)F", "/T", "/C")
    Invoke-Icacls @($p, "/grant:r", "${AgentUser}:(OI)(CI)RX", "/T", "/C")
    Invoke-Icacls @($p, "/grant:r", "SYSTEM:(OI)(CI)F", "/T", "/C")
    Write-Host "  read-only -> $p" -ForegroundColor Green
}

# --------------------------------------------------------------------------- #
# Part 2b: NO-access secrets (the agent cannot read the key or touch the audit)
# --------------------------------------------------------------------------- #
Write-Host "`n[2/4] Sealing secrets (no agent access: HMAC key, breakglass audit)..." -ForegroundColor Cyan
# NO access at all for the agent. inheritance removed + grant only owner+SYSTEM,
# so the agent is implicitly denied. Closes B16 (forge runtime key) and B17
# (reset breakglass audit) at the OS layer.
$noAccessPaths = @(
    (Join-Path $RepoRoot "runtime\.runtime_protection_key"),
    (Join-Path $RepoRoot ".git\thomas_skip_audit.jsonl"),
    (Join-Path $RepoRoot ".git\thomas_precommit_success.json")
)
foreach ($p in $noAccessPaths) {
    if (-not (Test-Path $p)) {
        Write-Host "  (not present yet; will be created owner-only): $p" -ForegroundColor DarkGray
        continue
    }
    Invoke-Icacls @($p, "/setowner", $OwnerUser, "/C")
    Invoke-Icacls @($p, "/inheritance:r")
    Invoke-Icacls @($p, "/grant:r", "${OwnerUser}:F", "/C")
    Invoke-Icacls @($p, "/grant:r", "SYSTEM:F", "/C")
    Write-Host "  sealed (owner-only) -> $p" -ForegroundColor Green
}

# --------------------------------------------------------------------------- #
# Part 2c: the one-way cage channels
# --------------------------------------------------------------------------- #
Write-Host "`n[3/4] Creating one-way cage channels at $CageRoot..." -ForegroundColor Cyan
$inbox = Join-Path $CageRoot "inbox"
$outbox = Join-Path $CageRoot "outbox"
$audit = Join-Path $CageRoot "audit"
$work = Join-Path $CageRoot "work"
$processed = Join-Path $CageRoot "processed"
foreach ($d in @($CageRoot, $inbox, $outbox, $audit, $work, $processed)) {
    if (-not (Test-Path $d)) {
        if ($PSCmdlet.ShouldProcess($d, 'New-Item Directory')) { New-Item -ItemType Directory -Path $d | Out-Null }
    }
}
# Base: owner + SYSTEM full, no inheritance, agent nothing — then add the two
# narrow cross-user grants below.
foreach ($d in @($CageRoot, $inbox, $outbox, $audit, $work, $processed)) {
    Invoke-Icacls @($d, "/inheritance:r")
    Invoke-Icacls @($d, "/grant:r", "${OwnerUser}:(OI)(CI)F")
    Invoke-Icacls @($d, "/grant:r", "SYSTEM:(OI)(CI)F")
}
# inbox: agent may WRITE submissions (create files/subdirs) but not read others
# back or delete them. Modify minus delete is approximated with Write+Read-exec;
# the master validates everything regardless.
Invoke-Icacls @($inbox, "/grant:r", "${AgentUser}:(OI)(CI)(WD,AD,WEA,WA,RX)")
# outbox: agent may READ verdicts only.
Invoke-Icacls @($outbox, "/grant:r", "${AgentUser}:(OI)(CI)RX")
# audit + work + processed: agent gets NOTHING (no grant) -> implicitly denied.
Write-Host "  inbox  (agent: write-only drop)  -> $inbox" -ForegroundColor Green
Write-Host "  outbox (agent: read-only verdict)-> $outbox" -ForegroundColor Green
Write-Host "  audit/work/processed (agent: no access)" -ForegroundColor Green

# --------------------------------------------------------------------------- #
# Done
# --------------------------------------------------------------------------- #
Write-Host "`n[4/4] Provisioning complete." -ForegroundColor Cyan
Write-Host @"

Next steps (see docs/CAGE_SETUP.md):
  1. Run the WORKER agent as '$AgentUser' (runas / scheduled task), with
     THOMAS_CAGE_ROOT=$CageRoot so it submits via:
        python scripts\forge\commit_master.py --cage-root "$CageRoot" submit ...
  2. Run the COMMIT-MASTER as '$OwnerUser' (you, holding the signing key behind
     Windows Hello):
        python scripts\forge\commit_master.py --cage-root "$CageRoot" watch
  3. Verify the boundary (read-only, safe to run anytime):
        powershell -File scripts\cage\verify_cage.ps1 -AgentUser $AgentUser -CageRoot "$CageRoot"
  4. Turn on the server-side backstop (Part 4): docs/BRANCH_PROTECTION_SETUP.md
"@ -ForegroundColor Gray
