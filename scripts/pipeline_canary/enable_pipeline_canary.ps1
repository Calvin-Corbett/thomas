# Watch Thomas's own checks: register ThomasPipelineCanary for you. No elevation.
#
# Run this once, in a normal (not elevated) PowerShell; running it again replaces the task. It registers a task for
# your account that runs the pipeline canary (python -m scripts.pipeline_canary once) every 5 minutes and at your
# sign-in, under pythonw (no window), only while you are signed in, never elevated, never twice at once, and for at
# most 20 minutes a pass.
#
# Each pass reads dev. When dev has moved and the move changed thomas/server/precard or thomas/server/proof, it measures
# the test selection of the last good commit and of dev's head on one fixed change, and on an alarm it tells you, turns
# the express window off, holds those folders, and puts the revert on your card. Its lines go to
# .thomas\pipeline_canary\canary.log in the checkout. See docs/superpowers/specs/2026-10-27-pipeline-canary-design.md.
#
# Rollback: Unregister-ScheduledTask -TaskName ThomasPipelineCanary -Confirm:$false

param(
    [string]$RepoRoot = "",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
$taskName = "ThomasPipelineCanary"

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

try {
    $pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) { throw "no pythonw at $pythonw" }
    $log = Join-Path $RepoRoot ".thomas\pipeline_canary\canary.log"
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m scripts.pipeline_canary once" -WorkingDirectory $RepoRoot
    $every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $signIn = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($every, $signIn) -Principal $principal `
        -Settings $settings -Force | Out-Null
    Say "  registered $taskName for $user (every 5 minutes and at sign-in, not elevated)"
    Start-ScheduledTask -TaskName $taskName
    Say "  first pass started; it sets the baseline. Its lines go to $log"
    Say "  to see its state: .venv\Scripts\python.exe -m scripts.pipeline_canary status"
    Say "RESULT: pipeline canary registered" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
