# Keep the cage's way out running: register ThomasCageKeepalive for you. No elevation.
#
# Run this once, in a normal (not elevated) PowerShell; running it again replaces the
# task. It registers a task for your account that runs scripts\cage\cage_keepalive.py
# every 15 minutes and at your sign-in, under pythonw (no window), only while you are
# signed in, never elevated, and never twice at once. Every line the keepalive writes
# is appended to C:\ProgramData\ThomasCage\keepalive.log.
#
# The keepalive starts ThomasSelfChangePromoter when nothing listens on 127.0.0.1:8897
# (the cage's egress proxy and search broker), and ThomasCagedServer when nothing
# listens on 8898 -- unless C:\ProgramData\ThomasCage\caged_server.off exists, the
# server's task is disabled, or code the server loads has uncommitted changes. It
# never ends a task.
#
# Nothing else is started here: only the keepalive's own first pass.
#
# Rollback: Unregister-ScheduledTask -TaskName ThomasCageKeepalive -Confirm:$false

param(
    [string]$RepoRoot = "",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
$taskName = "ThomasCageKeepalive"
$cageRoot = if ($env:THOMAS_CAGE_ROOT) { $env:THOMAS_CAGE_ROOT } else { "C:\ProgramData\ThomasCage" }

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

try {
    $pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) { throw "no pythonw at $pythonw" }
    if (-not (Test-Path -LiteralPath $cageRoot)) { throw "no cage folder at $cageRoot (enable_cage.ps1 makes it)" }
    $script = Join-Path $scriptDir "cage_keepalive.py"
    $log = Join-Path $cageRoot "keepalive.log"
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`" --log `"$log`"" -WorkingDirectory $RepoRoot
    $every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
    $signIn = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($every, $signIn) -Principal $principal `
        -Settings $settings -Force | Out-Null
    Say "  registered $taskName for $user (every 15 minutes and at sign-in, not elevated)"
    Start-ScheduledTask -TaskName $taskName
    Say "  first pass started; its lines go to $log"
    Say "  no keepalive.log yet is normal while both ports are up: it writes a line only when it acts."
    Say "  to see that its passes run: (Get-ScheduledTaskInfo -TaskName $taskName).LastTaskResult is 0"
    Say "  to keep the caged server stopped on purpose: New-Item $(Join-Path $cageRoot 'caged_server.off')"
    Say "RESULT: keepalive registered" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
