# Start the self-change promoter now and at every logon, as you. No elevation.
#
# The promoter (scripts/cage/self_change_promoter.py) is the only thing that puts
# a self-fix into the running Thomas, and only after you approve it at the Windows
# sign-in -- so it has to run in your session, where that prompt can appear. It
# holds a single-instance lock, beats a heartbeat into
# C:\ProgramData\ThomasCage\promoter, and logs there.

param(
    [string]$RepoRoot = "",
    [string]$StatusFile = "",
    [int]$WaitSeconds = 30
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
$taskName = "ThomasSelfChangePromoter"
$cageRoot = if ($env:THOMAS_CAGE_ROOT) { $env:THOMAS_CAGE_ROOT } else { "C:\ProgramData\ThomasCage" }

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

try {
    $pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) { throw "no pythonw at $pythonw" }
    $script = Join-Path $scriptDir "promoter_service.py"
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
    Say "  registered $taskName for $user (at logon, not elevated)"
    Start-ScheduledTask -TaskName $taskName

    $beat = Join-Path $cageRoot "promoter\promoter.heartbeat"
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $fresh = $false
    while ((Get-Date) -lt $deadline) {
        if ((Test-Path -LiteralPath $beat) -and ((Get-Date) - (Get-Item -LiteralPath $beat).LastWriteTime).TotalSeconds -lt 15) {
            $fresh = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $fresh) { throw "the promoter started but no heartbeat appeared at $beat" }
    Say "  heartbeat: $beat"
    Say "RESULT: promoter running" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
