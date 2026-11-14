<#
.SYNOPSIS
  Give the caged agent account the repo access it needs, and no write on
  Thomas's own code. Run once, elevated, after provision_cage.ps1.

.DESCRIPTION
  The cage account lives outside your profile, so by default it cannot even
  READ C:\Users\<you>\Thomas: a caged shell could not run a test or read a
  file. This grants exactly what a worker needs and nothing more:

    * read + execute on the whole repo (so it can run tests and read code)
    * write ONLY where agent work belongs: tests\, changelog.d\, plans\,
      docs\, runtime\, and the cage channels
    * NO write on Thomas's own code (thomas\, scripts\), agent_safety.toml or
      .git -- which is the point. Owner direction 2026-09-22: a shell command
      put a protected file back, around the card and the password. After this,
      a shell simply cannot: the approved path (the card, your PIN, then the
      server's own write) still can.

  Write is withheld, not denied: the agent gets read+execute and is granted
  modify only on the listed folders. No Deny ACEs, which are easy to get wrong
  and hard to read later.

.PARAMETER WhatIf
  Print every change without making one. Do this pass first: there is no
  rollback script.

.EXAMPLE
  .\scripts\cage\grant_repo_access.ps1 -WhatIf
  .\scripts\cage\grant_repo_access.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AgentUser = "thomas-agent",
    [string]$OwnerUser = $env:USERNAME,
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage"
)

$ErrorActionPreference = "Stop"
# $PSScriptRoot is empty while parameters bind when the script is run with
# -File, so the repo path is worked out here instead (it resolved to nothing
# and the script died before its own error handling, 2026-09-22).
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }


function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this from an elevated (Administrator) PowerShell."
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

Write-Host "== Cage repo access ==" -ForegroundColor Cyan
Write-Host "  Repo:  $RepoRoot"
Write-Host "  Agent: $AgentUser"
Write-Host "  Cage:  $CageRoot"
Assert-Admin

if (-not (Get-LocalUser -Name $AgentUser -ErrorAction SilentlyContinue)) {
    throw "$AgentUser does not exist. Run provision_cage.ps1 first."
}

# --------------------------------------------------------------------------- #
# 1. Read + execute on the repo (inherited by everything below it)
# --------------------------------------------------------------------------- #
Write-Host "`n[1/3] Read + execute on the repo..." -ForegroundColor Cyan
# No /T. (OI)(CI) is an inheritable ACE, and Windows propagates it to existing
# children in one kernel-side pass; /T additionally walks and rewrites every
# file itself. Measured 2026-09-22 on this repo: 19 minutes and 1,125 seconds
# of CPU for step 1 alone, because the walk includes .venv, .git and every
# runtime/benchmarks workspace. Same end state, seconds instead.
Invoke-Icacls @($RepoRoot, "/grant", "${AgentUser}:(OI)(CI)RX", "/C", "/Q")
Write-Host "  read-only -> $RepoRoot" -ForegroundColor Green

# --------------------------------------------------------------------------- #
# 2. Write where agent work belongs
# --------------------------------------------------------------------------- #
Write-Host "`n[2/3] Write where agent work belongs..." -ForegroundColor Cyan
$writable = @("tests", "changelog.d", "plans", "docs", "runtime")
foreach ($rel in $writable) {
    $path = Join-Path $RepoRoot $rel
    if (-not (Test-Path $path)) { Write-Warning "  skip (missing): $path"; continue }
    Invoke-Icacls @($path, "/grant", "${AgentUser}:(OI)(CI)M", "/C", "/Q")
    Write-Host "  writable -> $path" -ForegroundColor Green
}

# --------------------------------------------------------------------------- #
# 3. The shell channel: the server drops commands, the runner answers
# --------------------------------------------------------------------------- #
Write-Host "`n[3/3] Shell channel..." -ForegroundColor Cyan
$shellIn = Join-Path $CageRoot "shell\inbox"
$shellOut = Join-Path $CageRoot "shell\outbox"
foreach ($dir in @($shellIn, $shellOut)) {
    if (-not (Test-Path $dir)) {
        if ($PSCmdlet.ShouldProcess($dir, 'New-Item')) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }
}
# The runner reads requests and deletes each one when answered, so it needs
# modify on the inbox as well; a request is data, and nothing in it grants
# anything (scripts/cage/shell_runner.py).
Invoke-Icacls @((Join-Path $CageRoot "shell"), "/grant", "${AgentUser}:(OI)(CI)M", "/C", "/Q")
Write-Host "  channel -> $shellIn / $shellOut" -ForegroundColor Green

Write-Host "`nDone. Check it from the agent's side:" -ForegroundColor Cyan
Write-Host "  .\scripts\cage\verify_cage.ps1"
Write-Host "Then install the runner:" -ForegroundColor Cyan
Write-Host "  .\scripts\cage\install_shell_runner.ps1"
