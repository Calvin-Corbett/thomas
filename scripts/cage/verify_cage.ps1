<#
.SYNOPSIS
  Read-only audit of the Praxis cage. Safe to run anytime, no admin needed.

.DESCRIPTION
  Verifies the privilege boundary that provision_cage.ps1 sets up:
    * the worker account exists and is NOT an administrator
    * gate scripts / commit-master / agent_safety.toml are read-only to the agent
    * the runtime HMAC key and breakglass audit are NO-access to the agent
    * the one-way channels exist (inbox writable, outbox readable, audit sealed)

  Prints a PASS/WARN/FAIL line per check. Exit codes:
    0 = all checks pass (cage enforced)
    1 = one or more checks FAILED (boundary is broken)
    2 = cage not provisioned yet (agent account absent) - informational

.PARAMETER AgentUser
  Worker account name. Default: 'thomas-agent'.

.PARAMETER RepoRoot
  Thomas repo root. Default: the repo this script lives in.

.PARAMETER CageRoot
  Channel root. Default: C:\ProgramData\ThomasCage.
#>
[CmdletBinding()]
param(
    [string]$AgentUser = "thomas-agent",
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage"
)

$ErrorActionPreference = "Continue"

# Resolve RepoRoot in-body: $PSScriptRoot can be empty when evaluated inside a
# param default under some invocation styles, so fall back robustly.
if (-not $RepoRoot) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}
$fail = 0
$warn = 0

function Report {
    param([string]$Status, [string]$Message)
    $color = switch ($Status) { "PASS" { "Green" } "WARN" { "Yellow" } "FAIL" { "Red" } default { "Gray" } }
    Write-Host ("  [{0}] {1}" -f $Status, $Message) -ForegroundColor $color
    if ($Status -eq "FAIL") { $script:fail++ }
    if ($Status -eq "WARN") { $script:warn++ }
}

function Get-AgentAce {
    # Return the icacls ACE substring(s) that mention the agent for a path.
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $lines = & icacls $Path 2>$null
    return ($lines | Where-Object { $_ -match [regex]::Escape($AgentUser) })
}

function Test-NotWritable {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) { Report "WARN" "$Label missing: $Path"; return }
    $ace = Get-AgentAce -Path $Path
    if (-not $ace) {
        Report "PASS" "$Label : agent has no explicit grant (sealed) -> $Path"
        return
    }
    $joined = ($ace -join " ")
    if ($joined -match "\(F\)" -or $joined -match "\(M\)" -or $joined -match "\(W\)" -or $joined -match ":\(W") {
        Report "FAIL" "$Label : agent appears WRITABLE -> $joined"
    }
    else {
        Report "PASS" "$Label : agent read-only -> $joined"
    }
}

function Test-NoAccess {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) { Report "WARN" "$Label not present yet (will be owner-only on creation): $Path"; return }
    $ace = Get-AgentAce -Path $Path
    if (-not $ace) {
        Report "PASS" "$Label : agent has NO access -> $Path"
    }
    elseif (($ace -join " ") -match "\(N\)|\(DENY\)") {
        Report "PASS" "$Label : agent explicitly denied -> $Path"
    }
    else {
        Report "FAIL" "$Label : agent has access it should NOT -> $($ace -join ' ')"
    }
}

Write-Host "== Thomas cage verification ==" -ForegroundColor Cyan
Write-Host "  Repo:  $RepoRoot"
Write-Host "  Agent: $AgentUser"
Write-Host "  Cage:  $CageRoot`n"

# --- account ---------------------------------------------------------------- #
Write-Host "[account]" -ForegroundColor Cyan
$user = Get-LocalUser -Name $AgentUser -ErrorAction SilentlyContinue
if (-not $user) {
    Report "WARN" "worker account '$AgentUser' does not exist - cage not provisioned yet."
    Write-Host "`nCage not provisioned. Run (elevated): scripts\cage\provision_cage.ps1" -ForegroundColor Yellow
    exit 2
}
Report "PASS" "worker account '$AgentUser' exists."
$admins = Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
if ($admins -match "\\$AgentUser$") {
    Report "FAIL" "'$AgentUser' is an Administrator (must be non-admin)."
}
else {
    Report "PASS" "'$AgentUser' is not an administrator."
}

# --- read-only paths -------------------------------------------------------- #
Write-Host "`n[read-only to agent]" -ForegroundColor Cyan
Test-NotWritable (Join-Path $RepoRoot "scripts\forge\gates") "gate scripts"
Test-NotWritable (Join-Path $RepoRoot "scripts\forge\commit_master.py") "commit-master"
Test-NotWritable (Join-Path $RepoRoot "agent_safety.toml") "agent_safety.toml"
Test-NotWritable (Join-Path $RepoRoot ".git\hooks") ".git/hooks"
Test-NotWritable (Join-Path $RepoRoot ".git\config") ".git/config"

# --- sealed secrets --------------------------------------------------------- #
Write-Host "`n[sealed secrets - no agent access]" -ForegroundColor Cyan
Test-NoAccess (Join-Path $RepoRoot "runtime\.runtime_protection_key") "runtime HMAC key"
Test-NoAccess (Join-Path $RepoRoot ".git\thomas_skip_audit.jsonl") "breakglass audit"

# --- channels --------------------------------------------------------------- #
Write-Host "`n[one-way channels]" -ForegroundColor Cyan
$inbox = Join-Path $CageRoot "inbox"
$outbox = Join-Path $CageRoot "outbox"
$audit = Join-Path $CageRoot "audit"
if (Test-Path $inbox) {
    $ace = (Get-AgentAce -Path $inbox) -join " "
    if ($ace -match "\(W") { Report "PASS" "inbox writable by agent -> $ace" }
    else { Report "FAIL" "inbox not writable by agent -> $ace" }
}
else { Report "WARN" "inbox missing: $inbox" }
if (Test-Path $outbox) {
    $ace = (Get-AgentAce -Path $outbox) -join " "
    if ($ace -match "\(RX\)|\(R\)") { Report "PASS" "outbox readable by agent -> $ace" }
    else { Report "WARN" "outbox agent ACE unexpected -> $ace" }
}
else { Report "WARN" "outbox missing: $outbox" }
Test-NoAccess $audit "cage audit log dir"

# --- summary ---------------------------------------------------------------- #
Write-Host "`n== summary ==" -ForegroundColor Cyan
if ($fail -gt 0) {
    Write-Host "  $fail FAILED, $warn warnings. The cage boundary is INCOMPLETE." -ForegroundColor Red
    exit 1
}
elseif ($warn -gt 0) {
    Write-Host "  0 failed, $warn warnings (paths not yet created). Re-run after first use." -ForegroundColor Yellow
    exit 0
}
else {
    Write-Host "  All checks passed. The cage boundary is enforced." -ForegroundColor Green
    exit 0
}
