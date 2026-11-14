<#
.SYNOPSIS
  Set up your window: the checker account, its folders and fence, the window's record, and the new cards' pin.
  Run elevated, once. Safe to run again.

.DESCRIPTION
  Part 4 of docs/superpowers/specs/2026-10-12-praxis-production-line-design.md (sections 8.1, 8.4, 8.7, 8.8).

    1. The local account thomas-checker: not an administrator, a new random password every run that is never shown
       or stored (the scheduled task keeps it, as enable_caged_server.ps1 does for thomas-agent).
    1b. The local account thomas-runner (review B1): not an administrator, a new random password every run. A
        change's own tests run as this account, never as thomas-checker, so a hostile test cannot write an answer.
        Its credential is stored in thomas-checker's own credential store (which thomas-runner cannot read), and the
        checker launches each test process as thomas-runner (scripts\cage\checker_runner.py, checker_launch.py).
    2. C:\ProgramData\ThomasCheck, owned by Administrators, inheritance off:
         jobs     you modify, the checker reads                 (thomas-runner: no access)
         results  the checker modifies, you read                (thomas-runner: no access)
         copies   the checker and thomas-runner modify, you read (the test runs in a copy)
         state    the checker modifies, you read                (thomas-runner: no access)
       thomas-agent, the Build teams' account, has no entry anywhere in it, and thomas-runner may write only copies.
    3. C:\ProgramData\ThomasWindow, the window's record, owned by Administrators: you may create a file and never
       change or remove one; thomas-agent may read; nothing else may write.
    4. Read and run, never write, on your checkout for thomas-checker and thomas-runner. The two service directories
       receive recursive grants even when they do not inherit the checkout ACL; both accounts can read base Python.
    5. A firewall rule: thomas-checker reaches nothing but this machine.
    6. The scheduled task ThomasChecker: scripts\cage\checker_service.py from your checkout, as thomas-checker, at
       startup, restarted when it stops. You may start it; it is not started here until Part 4 has landed.
    7. The card catalogue pinned from -RepoRoot: the copy that adds open_window, open_window_away, undo_change and
       revert_change. While the running catalogue differs from the pin, every hand-in waits (nothing is asked or
       landed), so run this right after Part 4 lands (OWNER_STEPS.md).
    7b. -AwayWindows on|off|keep (keep when not given): whether a window you open with --away may keep landing while
       your PC is locked or you are away (your decision, 2026-10-22). On writes window.away ("on") into the pin folder,
       owned by Administrators, so only an elevated step like this one can turn it on; off removes it; keep leaves it
       as it is. A fresh install has none, so it is off until you turn it on here. Each such window still asks you at
       its own card, and says so.
    8. Every permission read back and checked, then, for up to -WaitMinutes, a wait for your checkout to hold the
       pinned catalogue. When it does: the caged server and the promoter are restarted and the checker started, and
       their heartbeats are checked. If the wait runs out, the setup stands and the restarts are left to the next run.

  -Plan prints every action and changes nothing (no elevation needed).

  Rollback (elevated): Unregister-ScheduledTask ThomasChecker; Remove-NetFirewallRule -Group "Thomas checker";
  Remove-LocalUser thomas-checker; Remove-LocalUser thomas-runner; remove C:\ProgramData\ThomasCheck; ThomasWindow is
  kept (it is the record). The hard off switch for every window is C:\ProgramData\ThomasPins\window.off: any content,
  placed elevated. Away windows off again: run this with -AwayWindows off (or remove ThomasPins\window.away, elevated).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cage\enable_window.ps1 -Plan
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$LiveRoot = "",
    [string]$CheckerUser = "thomas-checker",
    [string]$RunnerUser = "thomas-runner",
    [string]$AgentUser = "thomas-agent",
    [string]$CheckRoot = "C:\ProgramData\ThomasCheck",
    [string]$RecordRoot = "C:\ProgramData\ThomasWindow",
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    [int]$WaitMinutes = 20,
    [string]$StatusFile = "",
    [ValidateSet("keep", "on", "off")][string]$AwayWindows = "keep",
    [switch]$Plan
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
if (-not $LiveRoot) { $LiveRoot = Join-Path $env:USERPROFILE "Thomas" }
$icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
$taskName = "ThomasChecker"
$group = "Thomas checker"

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

try {
    . (Join-Path $scriptDir "window_setup_steps.ps1")  # Invoke-Acl, Set-FolderAcl, Assert-Writers, Set-CheckerCredential
    if (-not $Plan) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
                [Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "not elevated" }
        $ownerSid = $identity.User.Value
    }
    else { $ownerSid = "<your account>" }
    . (Join-Path $scriptDir "pin_folder.ps1")
    $catalogue = Join-Path $RepoRoot "scripts\cage\card_catalogue.py"
    if (-not (Test-Path -LiteralPath $catalogue)) { throw "no catalogue at $catalogue" }
    if (-not (Select-String -LiteralPath $catalogue -Pattern '"open_window": CardKind' -SimpleMatch -Quiet)) {
        throw "$catalogue has no open_window card: run this from a checkout that holds Part 4"
    }

    Say "== Your window: setup ==" "Cyan"
    # 1. The account.
    if ($Plan) { Say "PLAN: create or reset the local account $CheckerUser (password not shown, not stored), never an administrator" }
    else {
        Add-Type -AssemblyName System.Web
        $pw = [System.Web.Security.Membership]::GeneratePassword(28, 6)
        $secure = ConvertTo-SecureString $pw -AsPlainText -Force
        if (Get-LocalUser -Name $CheckerUser -ErrorAction SilentlyContinue) {
            Set-LocalUser -Name $CheckerUser -Password $secure
        }
        else {
            New-LocalUser -Name $CheckerUser -Password $secure -FullName "Thomas Checker" `
                -Description "Runs Thomas's checks (Part 4)" -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
        }
        if ((Get-LocalGroupMember -Group "Administrators" | ForEach-Object { $_.Name }) -match "\\$CheckerUser$") {
            Remove-LocalGroupMember -Group "Administrators" -Member $CheckerUser
        }
        $checkerSid = (Get-LocalUser -Name $CheckerUser).SID.Value
        $agentSid = (Get-LocalUser -Name $AgentUser).SID.Value
        Say "  $CheckerUser ready ($checkerSid); new password set, not shown, not stored"
    }
    if ($Plan) { $checkerSid = "<$CheckerUser>"; $agentSid = "<$AgentUser>" }
    $checker = "*${checkerSid}"
    $you = "*${ownerSid}"
    $agent = "*${agentSid}"

    # 1b. The runner account: a change's tests run as this, never as the checker that writes the answers (review B1).
    $credTarget = "Thomas-Checker-Runner"
    if ($Plan) { Say "PLAN: create or reset the local account $RunnerUser (password not shown), never an administrator" }
    else {
        $runnerPw = [System.Web.Security.Membership]::GeneratePassword(28, 6)
        $runnerSecure = ConvertTo-SecureString $runnerPw -AsPlainText -Force
        if (Get-LocalUser -Name $RunnerUser -ErrorAction SilentlyContinue) {
            Set-LocalUser -Name $RunnerUser -Password $runnerSecure
        }
        else {
            New-LocalUser -Name $RunnerUser -Password $runnerSecure -FullName "Thomas Test Runner" `
                -Description "Runs tests without writing checker answers" `
                -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
        }
        if ((Get-LocalGroupMember -Group "Administrators" | ForEach-Object { $_.Name }) -match "\\$RunnerUser$") {
            Remove-LocalGroupMember -Group "Administrators" -Member $RunnerUser
        }
        $runnerSid = (Get-LocalUser -Name $RunnerUser).SID.Value
        Say "  $RunnerUser ready ($runnerSid); new password set, not shown"
    }
    if ($Plan) { $runnerSid = "<$RunnerUser>" }
    $runner = "*${runnerSid}"

    Grant-CheckerBatchLogon $checkerSid

    # 2. The checker's folders. The runner may write only copies (it runs the tests there); it has no entry on jobs,
    #    results or state, so a change's test cannot read a job or write an answer (review B1).
    Set-FolderAcl $CheckRoot @("${you}:RX", "${checker}:RX", "${runner}:RX")
    Set-FolderAcl (Join-Path $CheckRoot "jobs") @("${you}:(OI)(CI)M", "${checker}:(OI)(CI)RX")
    Set-FolderAcl (Join-Path $CheckRoot "results") @("${checker}:(OI)(CI)M", "${you}:(OI)(CI)RX")
    Set-FolderAcl (Join-Path $CheckRoot "state") @("${checker}:(OI)(CI)M", "${you}:(OI)(CI)RX")
    Set-FolderAcl (Join-Path $CheckRoot "copies") @("${checker}:(OI)(CI)M", "${runner}:(OI)(CI)M", "${you}:(OI)(CI)RX")
    Say "  checker folders set: $CheckRoot"

    # 3. The record: you may create a file, never change or remove one.
    Set-FolderAcl $RecordRoot @("${you}:(CI)(RX,WD,AD)", "${you}:(OI)(IO)(R)", "*S-1-3-4:(OI)(CI)(R)", "${agent}:(OI)(CI)(RX)")
    Say "  record folder set: $RecordRoot"

    # 4. Read and run on your checkout, for both the checker and the runner (the runner runs the tests in a copy
    #    that shares your checkout's git objects, so it must read them).
    Invoke-Acl @($LiveRoot, "/grant", "${checker}:(OI)(CI)RX", "${runner}:(OI)(CI)RX", "/C", "/Q")
    # A checkout root grant does not reach service directories with inheritance disabled.
    foreach ($serviceDir in @('scripts\cage', 'scripts\forge\gates')) {
        $servicePath = Join-Path $LiveRoot $serviceDir
        if (-not $Plan -and -not (Test-Path -LiteralPath $servicePath -PathType Container)) {
            throw "missing checker service directory: $servicePath"
        }
        Invoke-Acl @($servicePath, '/grant', "${checker}:(OI)(CI)RX", "${runner}:(OI)(CI)RX", '/T', '/C', '/Q')
    }
    Grant-WindowPythonRead $LiveRoot @("${checker}:(OI)(CI)RX", "${runner}:(OI)(CI)RX")
    Say "  $CheckerUser and $RunnerUser read $LiveRoot"

    # 4b. The runner's credential, kept in the checker's own credential store (thomas-runner cannot read it), and the
    #     identity file the checker reads to learn which account to launch tests as (scripts\cage\checker_runner.py).
    if ($Plan) {
        Say "PLAN: store the runner logon ($RunnerUser) in ${CheckerUser}'s credential store under '$credTarget'"
        Say "PLAN: write $CheckRoot\state\runner.json naming $RunnerUser and the credential '$credTarget'"
    }
    else {
        Set-CheckerCredential -CheckerUser $CheckerUser -CheckerPassword $pw -Target $credTarget `
            -RunnerAccount ("{0}\{1}" -f $env:COMPUTERNAME, $RunnerUser) -RunnerPassword $runnerPw
        $runnerPw = $null
        $config = @{ schema = 1; account = ("{0}\{1}" -f $env:COMPUTERNAME, $RunnerUser); credential = $credTarget }
        $json = $config | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText((Join-Path $CheckRoot "state\runner.json"), $json,
            (New-Object System.Text.UTF8Encoding($false)))
        Say "  runner identity recorded; credential stored in ${CheckerUser}'s store"
    }

    # 5. The fence.
    $remote = @("0.0.0.0-126.255.255.255", "128.0.0.0-255.255.255.255", "::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff")
    if ($Plan) { Say "PLAN: firewall: block every connection out for $CheckerUser except this machine (group '$group')" }
    else {
        Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName "Thomas checker: no connections out" -Group $group -Direction Outbound `
            -Action Block -Profile Any -RemoteAddress $remote -LocalUser "D:(A;;CC;;;$checkerSid)" `
            -Description "The checker account ($CheckerUser) reaches nothing but this machine." | Out-Null
        Say "  fence set for $CheckerUser"
    }

    # 6. The task.
    $pythonw = Join-Path $LiveRoot ".venv\Scripts\pythonw.exe"
    $service = Join-Path $LiveRoot "scripts\cage\checker_service.py"
    if ($Plan) { Say "PLAN: scheduled task $taskName runs `"$service`" with $pythonw as $CheckerUser, Limited, at startup, from $LiveRoot" }
    else {
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$service`"" -WorkingDirectory $LiveRoot
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -MultipleInstances IgnoreNew
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
            -Settings $settings -User ("{0}\{1}" -f $env:COMPUTERNAME, $CheckerUser) -Password $pw -RunLevel Limited `
            -Description "Thomas's checker (Part 4): runs a change's tests as its own account." | Out-Null
        $pw = $null
        $scheduler = New-Object -ComObject Schedule.Service
        $scheduler.Connect()
        $task = $scheduler.GetFolder("\").GetTask($taskName)
        $sddl = $task.GetSecurityDescriptor(4)
        if ($sddl -notlike "*(A;;GRGX;;;$ownerSid)*") { $task.SetSecurityDescriptor($sddl + "(A;;GRGX;;;$ownerSid)", 0) }
        Say "  task $taskName registered (not started)"
    }

    # 7. The pin.
    if ($Plan) { Say "PLAN: pin catalogue.sha256 in $PinRoot from $catalogue" }
    else {
        $digest = Get-NormalizedSha256 -Path $catalogue
        Initialize-PinFolder -PinRoot $PinRoot
        Write-PinFile -PinRoot $PinRoot -Name "catalogue.sha256" -Value $digest | Out-Null
        Say "  cards pinned: $digest"
    }

    # 7b. Keeping a window landing while you are away: off unless you turn it on here (window_state.away_allowed).
    $awayPath = Join-Path $PinRoot "window.away"
    if ($AwayWindows -eq "on") {
        if ($Plan) { Say "PLAN: turn ON keeping a window landing while you are away: window.away (on) in $PinRoot, owned by Administrators" }
        else {
            Initialize-PinFolder -PinRoot $PinRoot
            Write-PinFile -PinRoot $PinRoot -Name "window.away" -Value "on" | Out-Null
            & $icacls $awayPath /setowner "*S-1-5-32-544" /Q | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "icacls /setowner returned $LASTEXITCODE for $awayPath" }
            Say "  away windows: ON for this PC (window.away in $PinRoot); each one is still asked for at its own card"
        }
    }
    elseif ($AwayWindows -eq "off") {
        if ($Plan) { Say "PLAN: turn OFF keeping a window landing while you are away: remove window.away from $PinRoot" }
        else {
            if (Test-Path -LiteralPath $awayPath) { Remove-Item -LiteralPath $awayPath -Force }
            Say "  away windows: off for this PC"
        }
    }
    else {
        $awayNow = if (Test-Path -LiteralPath $awayPath) { "on (left as it is)" } else { "off (the default)" }
        Say ("$(if ($Plan) { 'PLAN: ' })away windows: $awayNow; -AwayWindows on or off changes it")
    }

    # 8. Read back, then wait for the landing.
    Assert-Writers $CheckRoot @()
    Assert-Writers (Join-Path $CheckRoot "jobs") @($ownerSid)
    Assert-Writers (Join-Path $CheckRoot "results") @($checkerSid)
    Assert-Writers (Join-Path $CheckRoot "state") @($checkerSid)
    # Only the checker and the runner may write copies: the runner runs the tests there, and nowhere else (review B1).
    Assert-Writers (Join-Path $CheckRoot "copies") @($checkerSid, $runnerSid)
    Assert-Writers $RecordRoot @($ownerSid)
    if ($Plan) { Say "PLAN: wait up to $WaitMinutes minutes for $LiveRoot to hold the pinned catalogue, then restart ThomasCagedServer and ThomasSelfChangePromoter and start $taskName"; return }
    $live = Join-Path $LiveRoot "scripts\cage\card_catalogue.py"
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    $landed = $false
    while ((Get-Date) -lt $deadline) {
        if ((Test-Path -LiteralPath $live) -and ((Get-NormalizedSha256 -Path $live) -eq $digest)) { $landed = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $landed) {
        Say "RESULT: set up and pinned; Part 4 has not landed yet, so nothing was restarted. Run this again after it lands." "Yellow"
        return
    }
    foreach ($name in @("ThomasCagedServer", "ThomasSelfChangePromoter")) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName $name
        Say "  restarted $name"
    }
    Start-ScheduledTask -TaskName $taskName
    $beat = Join-Path $CheckRoot "state\heartbeat"
    $fence = Join-Path $CheckRoot "state\fence.json"
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        if ((Test-Path -LiteralPath $beat) -and (Test-Path -LiteralPath $fence)) { $ready = $true; break }
    }
    if (-not $ready) { throw "the checker did not start beating at $beat" }
    if (-not ((Get-Content -LiteralPath $fence -Raw | ConvertFrom-Json).fenced)) { throw "the checker can reach past this machine: the fence did not hold" }
    Say "RESULT: your window is set up; the checker is running and fenced" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
