<#
.SYNOPSIS
  Install the caged shell runner as a scheduled task running as the agent
  account. Run once, elevated, after grant_repo_access.ps1.

.DESCRIPTION
  This is the step that makes the cage real: from here on Thomas's shell
  commands execute as 'thomas-agent', which can read and execute the repo but
  cannot write Thomas's own code. Owner direction 2026-09-22: "The thing that
  stops Thomas from breaking his rules is not words. It's hard gates."

  You are asked for the agent account's password once, at Windows' own
  credential prompt. It goes straight to Task Scheduler, which stores it in the
  Windows credential store. It is never written to a file, never printed, and
  never visible to Thomas -- he has no way to read another account's stored
  task credential.

  The task starts at boot and is started here too, so the runner is alive
  immediately. It writes a heartbeat the server watches: when the runner is not
  answering and [tools] cage_shell is 'required', the shell refuses rather than
  running anything with your account.

.PARAMETER Uninstall
  Remove the task (the shell then falls back to whatever cage_shell says).

.EXAMPLE
  .\scripts\cage\install_shell_runner.ps1
  .\scripts\cage\install_shell_runner.ps1 -Uninstall
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AgentUser = "thomas-agent",
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$TaskName = "ThomasCageShellRunner",
    [switch]$Uninstall
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

Assert-Admin

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister-ScheduledTask')) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "Removed $TaskName." -ForegroundColor Green
        }
    }
    else { Write-Host "$TaskName is not installed." -ForegroundColor Yellow }
    return
}

$python = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = "pythonw.exe" }
$runner = Join-Path $scriptDir "shell_runner.py"
if (-not (Test-Path $runner)) { throw "missing runner: $runner" }

Write-Host "== Install caged shell runner ==" -ForegroundColor Cyan
Write-Host "  Task:    $TaskName"
Write-Host "  Runs as: $AgentUser"
Write-Host "  Python:  $python"
Write-Host "  Runner:  $runner"
Write-Host "  Cage:    $CageRoot"
Write-Host ""
Write-Host "Windows will ask for $AgentUser's password (the one provision_cage.ps1" -ForegroundColor Yellow
Write-Host "printed into your vault). It is stored by Task Scheduler, not by Thomas." -ForegroundColor Yellow

$cred = Get-Credential -UserName $AgentUser -Message "Password for $AgentUser (the caged worker account)"

$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}" --cage-root "{1}"' -f $runner, $CageRoot) -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited `
        -Description "Runs Thomas's shell commands as the caged agent account (see docs/CAGE_SETUP.md)." | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "`nInstalled and started." -ForegroundColor Green
}

Start-Sleep -Seconds 3
$beat = Join-Path $CageRoot "shell\runner.heartbeat"
if (Test-Path $beat) {
    Write-Host "Heartbeat is live: $beat" -ForegroundColor Green
    Write-Host "`nThomas's shell now runs as $AgentUser. To make that the rule rather" -ForegroundColor Cyan
    Write-Host "than the default, set [tools] cage_shell = 'required' in thomas.toml." -ForegroundColor Cyan
}
else {
    Write-Warning "No heartbeat yet at $beat."
    Write-Warning "Check: Get-ScheduledTaskInfo -TaskName $TaskName   (LastTaskResult 0 = running)"
    Write-Warning "A common cause is $AgentUser lacking 'Log on as a batch job' rights."
}
