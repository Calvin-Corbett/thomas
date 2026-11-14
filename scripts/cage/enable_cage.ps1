<#
.SYNOPSIS
  Turn the cage on in one elevated run: repo access, a fresh agent credential,
  and the shell runner installed and started.

.DESCRIPTION
  Owner direction, 2026-09-22: "Whatever you need to happen, you can trigger it
  through a command through a password thing... Stop trying to make me do
  stuff." So this does every step itself. The owner approves the elevation
  prompt; nothing else is asked of them, and they never type or look up a
  password.

  The agent account's password is rotated here to a fresh random value, handed
  straight to Task Scheduler, and dropped. It is never printed, never written to
  a file, and never returned -- so it cannot reach Thomas, a log or a transcript.
  An administrator can set a local account's password without knowing the old
  one, which is what makes that possible.

  Steps: grant_repo_access.ps1 (read+execute on the repo, write only where agent
  work belongs, channel permissions), then register and start the runner task as
  the agent account, then confirm its heartbeat.

.EXAMPLE
  # Launched elevated by the agent; the owner just approves the prompt.
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cage\enable_cage.ps1
#>
[CmdletBinding()]
param(
    [string]$AgentUser = "thomas-agent",
    [string]$RepoRoot = "",
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$TaskName = "ThomasCageShellRunner",
    [string]$StatusFile = "",
    # Repo permissions are the slow part (minutes: an inheritable ACE still has
    # to reach every file under .venv, .git and runtime/benchmarks) and they do
    # not change between attempts. Skip them when retrying a failed runner.
    [switch]$SkipPermissions
)

$ErrorActionPreference = "Stop"
# $PSScriptRoot is empty while parameters bind when the script is run with
# -File, so the repo path is worked out here instead (it resolved to nothing
# and the script died before its own error handling, 2026-09-22).
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "not elevated"
    }
    Say "== Enabling the Thomas cage ==" "Cyan"
    Say "  repo:  $RepoRoot"
    Say "  agent: $AgentUser"

    $agentAccount = Get-LocalUser -Name $AgentUser -ErrorAction SilentlyContinue
    if (-not $agentAccount) {
        throw "$AgentUser does not exist; run provision_cage.ps1 first."
    }

    # 0. The right to log on as a batch job.
    #
    # A task that runs as another account with a stored password performs a
    # BATCH logon, and a fresh local user does not hold SeBatchLogonRight. Task
    # Scheduler registers the task, accepts the credential, and then never runs
    # it: the only trace is LastTaskResult 267011 (SCHED_S_TASK_HAS_NOT_RUN).
    # Measured here 2026-09-22 -- the cage looked installed while nothing was
    # caged, which is the one way this may never fail.
    #
    # Granted through LSA rather than a secedit export/import round trip: that
    # rewrites the whole USER_RIGHTS area from a text dump, and anything the
    # export missed comes back changed. This adds one right to one account.
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;

public class ThomasCageLsa {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING { public UInt16 Length; public UInt16 MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES {
        public int Length; public IntPtr RootDirectory; public IntPtr ObjectName;
        public uint Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService;
    }
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint LsaOpenPolicy(IntPtr SystemName, ref LSA_OBJECT_ATTRIBUTES oa, int access, out IntPtr policy);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint LsaAddAccountRights(IntPtr policy, byte[] sid, LSA_UNICODE_STRING[] rights, int count);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
    [DllImport("advapi32.dll")] static extern int LsaNtStatusToWinError(uint status);

    public static void Grant(string sidString, string right) {
        SecurityIdentifier sid = new SecurityIdentifier(sidString);
        byte[] sidBytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(sidBytes, 0);
        LSA_OBJECT_ATTRIBUTES oa = new LSA_OBJECT_ATTRIBUTES();
        oa.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));
        IntPtr policy;
        // POLICY_CREATE_ACCOUNT | POLICY_LOOKUP_NAMES
        uint st = LsaOpenPolicy(IntPtr.Zero, ref oa, 0x00000010 | 0x00000800, out policy);
        if (st != 0) throw new Exception("LsaOpenPolicy failed with " + LsaNtStatusToWinError(st));
        try {
            LSA_UNICODE_STRING[] rights = new LSA_UNICODE_STRING[1];
            rights[0].Buffer = Marshal.StringToHGlobalUni(right);
            rights[0].Length = (UInt16)(right.Length * 2);
            rights[0].MaximumLength = (UInt16)((right.Length + 1) * 2);
            st = LsaAddAccountRights(policy, sidBytes, rights, 1);
            Marshal.FreeHGlobal(rights[0].Buffer);
            if (st != 0) throw new Exception("LsaAddAccountRights failed with " + LsaNtStatusToWinError(st));
        } finally { LsaClose(policy); }
    }
}
"@ -ErrorAction SilentlyContinue
    [ThomasCageLsa]::Grant($agentAccount.SID.Value, "SeBatchLogonRight")
    Say "  batch logon right granted to $AgentUser" "Green"

    # 1. Repo + channel permissions.
    if ($SkipPermissions) {
        Say "  permissions skipped (-SkipPermissions)" "Yellow"
    }
    else {
        & (Join-Path $scriptDir "grant_repo_access.ps1") -AgentUser $AgentUser -RepoRoot $RepoRoot -CageRoot $CageRoot
        Say "  permissions applied" "Green"
    }

    # 2. A fresh credential for the task, used once and dropped.
    Add-Type -AssemblyName System.Web
    $pw = [System.Web.Security.Membership]::GeneratePassword(28, 6)
    Set-LocalUser -Name $AgentUser -Password (ConvertTo-SecureString $pw -AsPlainText -Force)
    Say "  agent credential rotated (not printed, not stored)" "Green"

    # 2b. The interpreter the runner is started with.
    #
    # A virtualenv's Scripts\pythonw.exe is a launcher: pyvenv.cfg points `home`
    # at the base installation, and the standard library is read from there. On
    # this machine that base install sits inside the owner's profile, where the
    # caged account has no access at all -- so the interpreter cannot start, and
    # under pythonw it cannot say so either. The task registers, runs, and dies
    # with no heartbeat and nothing in any log (measured 2026-09-22).
    #
    # The path is read from pyvenv.cfg rather than assumed, so this follows the
    # venv wherever it was built from. Read+execute only.
    $venvCfg = Join-Path $RepoRoot ".venv\pyvenv.cfg"
    if (Test-Path $venvCfg) {
        $pyHome = ((Get-Content $venvCfg | Where-Object { $_ -match '^\s*home\s*=' }) -replace '^\s*home\s*=\s*', '').Trim()
        if ($pyHome -and (Test-Path $pyHome)) {
            & icacls $pyHome /grant "${AgentUser}:(OI)(CI)RX" /C /Q | Out-Null
            Say "  base python readable: $pyHome" "Green"
        }
        else { Say "  pyvenv.cfg names no readable home; runner may not start" "Yellow" }
    }

    # 2c. Let the caged account READ git's config, and trust the repo.
    #
    # Two separate refusals, both measured 2026-09-22 against the live cage:
    #
    #   .git\config had inheritance stripped and only SYSTEM and the owner
    #   granted. That makes it unwritable by the agent, which is the point --
    #   it must not be able to change a remote or a hook. But git reads its
    #   config before doing anything at all, so the agent could not run `git
    #   status`, `log` or `diff` either. Read is restored; write is not, and
    #   `git config --local` still answers "could not lock config file".
    #
    #   git also refuses a repository owned by another user ("dubious
    #   ownership"). --system rather than --global, because the agent's own
    #   profile is created on first logon and may not exist yet.
    $gitCfg = Join-Path $RepoRoot ".git\config"
    if (Test-Path $gitCfg) {
        & icacls $gitCfg /grant "${AgentUser}:(R)" /C /Q | Out-Null
        Say "  git config readable (read only; it still cannot be written)" "Green"
    }
    $repoForGit = $RepoRoot -replace '\\', '/'
    $alreadySafe = (& git config --system --get-all safe.directory 2>$null) -contains $repoForGit
    if (-not $alreadySafe) {
        & git config --system --add safe.directory $repoForGit 2>$null
        if ($LASTEXITCODE -eq 0) { Say "  repo marked safe.directory for every account" "Green" }
        else { Say "  could not set safe.directory; git may refuse in the cage" "Yellow" }
    }
    # Self-fixes are made in green clones the server creates as you, so git run by
    # the agent account there sees another owner and refuses. Green's git folders
    # are read-only to the agent; this lets it read them (git 2.46+ wildcard).
    $greenForGit = (Join-Path $env:LOCALAPPDATA "Thomas\green").Replace('\', '/') + "/*"
    if (-not ((& git config --system --get-all safe.directory 2>$null) -contains $greenForGit)) {
        & git config --system --add safe.directory $greenForGit 2>$null
        if ($LASTEXITCODE -eq 0) { Say "  green clones marked safe.directory" "Green" }
        else { Say "  could not mark green clones safe; git in the cage will refuse there" "Yellow" }
    }

    # 3. The runner task, as the agent account.
    $python = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $python)) { $python = "pythonw.exe" }
    $runner = Join-Path $scriptDir "shell_runner.py"
    if (-not (Test-Path $runner)) { throw "missing runner: $runner" }

    $action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}" --cage-root "{1}"' -f $runner, $CageRoot) -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User ("{0}\{1}" -f $env:COMPUTERNAME, $AgentUser) -Password $pw -RunLevel Limited `
        -Description "Runs Thomas's shell commands as the caged agent account (docs/CAGE_SETUP.md)." | Out-Null
    $pw = $null
    Start-ScheduledTask -TaskName $TaskName
    Say "  task registered and started" "Green"

    # 4. Prove it is alive.
    $beat = Join-Path $CageRoot "shell\runner.heartbeat"
    $alive = $false
    # 30s, not 10: a cold Python start behind a first-ever batch logon (profile
    # creation included) is comfortably slower than ten seconds, and reporting
    # "not answering" for a runner that was merely still starting sends the
    # next person looking for a fault that is not there.
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        if (Test-Path $beat) { $alive = $true; break }
    }
    if ($alive) {
        Say "  heartbeat live: $beat" "Green"
        Say "RESULT: cage on" "Green"
    }
    else {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        Say ("  no heartbeat; LastTaskResult=" + $info.LastTaskResult) "Yellow"
        Say "RESULT: task installed, runner not answering" "Yellow"
    }
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { $lines -join "`r`n" | Set-Content -Path $StatusFile -Encoding utf8 } catch { }
    }
}
