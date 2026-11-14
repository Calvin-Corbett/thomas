# Register the caged Thomas server (Project 4a): the ordinary server, run as the
# cage account on its own port, beside your usual server. Run elevated, once.
#
#   1. a fresh random password for the cage account -- never shown, never stored;
#      Task Scheduler keeps it for the two tasks that need it
#   2. the shell runner re-registered with it (the old stored password stops
#      working the moment it changes), which also reloads the runner's code
#   3. ThomasCagedServer: scripts\cage\caged_server.py as the cage account, on
#      port 8898, started by hand -- no trigger, so nothing changes at logon
#   4. you may start and stop both tasks without elevation from now on (the
#      wall is against the agent, not against you)
#   5. both started, and proven: the runner's heartbeat is fresh and the caged
#      server answers /api/health on its port
#
# Rollback: Unregister-ScheduledTask ThomasCagedServer. Your server on 8899 is
# never touched.

param(
    [string]$RepoRoot = "",
    [string]$AgentUser = "thomas-agent",
    [int]$Port = 8898,
    [string]$CodexHome = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
if (-not $CodexHome) { $CodexHome = Join-Path $env:USERPROFILE ".codex" }

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

function Allow-Owner([string]$TaskName, [string]$OwnerSid) {
    # Read + run for you on this task, so Start-/Stop-ScheduledTask work unelevated.
    $service = New-Object -ComObject Schedule.Service
    $service.Connect()
    $task = $service.GetFolder("\").GetTask($TaskName)
    $sddl = $task.GetSecurityDescriptor(4)
    $ace = "(A;;GRGX;;;$OwnerSid)"
    if ($sddl -notlike "*$ace*") { $task.SetSecurityDescriptor($sddl + $ace, 0) }
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "not elevated"
    }
    $ownerSid = $identity.User.Value
    $venv = Join-Path $RepoRoot ".venv\Scripts"
    $account = "{0}\{1}" -f $env:COMPUTERNAME, $AgentUser

    Add-Type -AssemblyName System.Web
    $pw = [System.Web.Security.Membership]::GeneratePassword(28, 6)
    Set-LocalUser -Name $AgentUser -Password (ConvertTo-SecureString $pw -AsPlainText -Force)
    Say "  new password set for $AgentUser (not shown, not stored)"

    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew

    # The runner, exactly as enable_cage.ps1 registers it.
    $runnerTask = "ThomasCageShellRunner"
    $runnerAction = New-ScheduledTaskAction -Execute (Join-Path $venv "pythonw.exe") `
        -Argument ('"{0}" --cage-root "{1}"' -f (Join-Path $scriptDir "shell_runner.py"), $CageRoot) -WorkingDirectory $RepoRoot
    if (Get-ScheduledTask -TaskName $runnerTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $runnerTask -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $runnerTask -Confirm:$false
    }
    Register-ScheduledTask -TaskName $runnerTask -Action $runnerAction -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Settings $settings -User $account -Password $pw -RunLevel Limited `
        -Description "Runs Thomas's shell commands as the caged agent account (docs/CAGE_SETUP.md)." | Out-Null
    Allow-Owner $runnerTask $ownerSid
    Say "  runner re-registered"

    $serverTask = "ThomasCagedServer"
    $serverArgs = '"{0}" --port {1} --codex-home "{2}"' -f (Join-Path $scriptDir "caged_server.py"), $Port, $CodexHome
    $serverAction = New-ScheduledTaskAction -Execute (Join-Path $venv "python.exe") -Argument $serverArgs -WorkingDirectory $RepoRoot
    if (Get-ScheduledTask -TaskName $serverTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $serverTask -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $serverTask -Confirm:$false
    }
    Register-ScheduledTask -TaskName $serverTask -Action $serverAction -Settings $settings -User $account `
        -Password $pw -RunLevel Limited `
        -Description "Thomas's server as the cage account, on port $Port (Project 4a); started by hand." | Out-Null
    $pw = $null
    Allow-Owner $serverTask $ownerSid
    Say "  caged server registered on port $Port"

    # Old runner processes (several may linger from earlier restarts) go first, so
    # the fresh one takes the channel's lock with the new code.
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*shell_runner.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-ScheduledTask -TaskName $runnerTask
    Start-ScheduledTask -TaskName $serverTask

    $beat = Join-Path $CageRoot "shell\runner.heartbeat"
    $runnerAlive = $false
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        if ((Test-Path $beat) -and (((Get-Date) - (Get-Item $beat).LastWriteTime).TotalSeconds -lt 10)) { $runnerAlive = $true; break }
    }
    if (-not $runnerAlive) { throw "the runner did not start beating at $beat" }
    Say "  runner beating"

    $health = $null
    foreach ($i in 1..120) {
        Start-Sleep -Seconds 1
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3; break } catch { }
    }
    if (-not $health) { throw "the caged server did not answer on port $Port within 2 minutes" }
    Say "  caged server answering on $Port (pid $($health.pid))"
    Say "RESULT: caged server running" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
