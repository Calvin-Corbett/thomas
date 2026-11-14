# The helper functions of enable_window.ps1, dot-sourced by it (kept apart for room). They read the caller's $Plan
# and $icacls and write through its Say, so they run only inside enable_window.ps1.

function Invoke-Acl([string[]]$IcaclsArgs) {
    if ($Plan) { Say ("PLAN: icacls " + ($IcaclsArgs -join ' ')); return }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $icacls @IcaclsArgs 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw ("icacls returned $LASTEXITCODE for: " + ($IcaclsArgs -join ' ')) }
    }
    finally { $ErrorActionPreference = $previous }
}

function Grant-CheckerBatchLogon([string]$CheckerSid) {
    if ($Plan) { Say "PLAN: grant SeBatchLogonRight to $CheckerUser before registering its tasks"; return }
    # Task Scheduler stores the password but will not run the task without this LSA right.
    # Add the one right directly; do not import a secedit dump of all user rights.
    if (-not ('ThomasWindowLsa' -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;
public class ThomasWindowLsa {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING { public UInt16 Length; public UInt16 MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES {
        public int Length; public IntPtr RootDirectory; public IntPtr ObjectName;
        public uint Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService;
    }
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint LsaOpenPolicy(IntPtr system, ref LSA_OBJECT_ATTRIBUTES oa, int access, out IntPtr policy);
    [DllImport("advapi32.dll")]
    static extern uint LsaAddAccountRights(IntPtr policy, byte[] sid, LSA_UNICODE_STRING[] rights, int count);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
    [DllImport("advapi32.dll")] static extern int LsaNtStatusToWinError(uint status);
    public static void Grant(string sidString) {
        SecurityIdentifier sid = new SecurityIdentifier(sidString);
        byte[] sidBytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(sidBytes, 0);
        LSA_OBJECT_ATTRIBUTES oa = new LSA_OBJECT_ATTRIBUTES();
        oa.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));
        IntPtr policy;
        uint st = LsaOpenPolicy(IntPtr.Zero, ref oa, 0x00000010 | 0x00000800, out policy);
        if (st != 0) throw new Exception("LsaOpenPolicy failed with " + LsaNtStatusToWinError(st));
        try {
            LSA_UNICODE_STRING right = new LSA_UNICODE_STRING();
            right.Buffer = Marshal.StringToHGlobalUni("SeBatchLogonRight");
            right.Length = (UInt16)("SeBatchLogonRight".Length * 2);
            right.MaximumLength = (UInt16)(("SeBatchLogonRight".Length + 1) * 2);
            try { st = LsaAddAccountRights(policy, sidBytes, new LSA_UNICODE_STRING[] { right }, 1); }
            finally { Marshal.FreeHGlobal(right.Buffer); }
            if (st != 0) throw new Exception("LsaAddAccountRights failed with " + LsaNtStatusToWinError(st));
        } finally { LsaClose(policy); }
    }
}
"@
    }
    [ThomasWindowLsa]::Grant($CheckerSid)
    Say "  batch logon right granted to $CheckerUser"
}

function Grant-WindowPythonRead([string]$LiveRoot, [string[]]$Accounts) {
    $config = Join-Path $LiveRoot ".venv\pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        if ($Plan) { Say "PLAN: read Python home from $config and grant both accounts recursive RX there"; return }
        throw "no Python venv config at $config"
    }
    $homeLine = Get-Content -LiteralPath $config | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
    if (-not $homeLine) { throw "no Python home in $config" }
    $pythonHome = ($homeLine -split '=', 2)[1].Trim()
    if (-not [IO.Path]::IsPathRooted($pythonHome) -or -not (Test-Path -LiteralPath (Join-Path $pythonHome 'python.exe') -PathType Leaf)) {
        throw "Python home in $config has no python.exe: $pythonHome"
    }
    Invoke-Acl (@($pythonHome, '/grant') + $Accounts + @('/T', '/C', '/Q'))
    Say "  $CheckerUser and $RunnerUser can read base Python at $pythonHome"
}

function Initialize-AdminFolder([string]$Path) {
    if ($Plan) { Say "PLAN: create $Path owned by Administrators"; return }
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path -Force | Out-Null }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$Path is a link; nothing was changed" }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & takeown /F $Path /A 2>$null | Out-Null
        & $icacls $Path /setowner "*S-1-5-32-544" /C /Q 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls /setowner returned $LASTEXITCODE for $Path" }
    }
    finally { $ErrorActionPreference = $previous }
}

function Set-FolderAcl([string]$Path, [string[]]$Grants) {
    Initialize-AdminFolder $Path
    Invoke-Acl (@($Path, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F") + $Grants + @("/Q"))
}

function Assert-Writers([string]$Path, [string[]]$Allowed) {
    # Only SYSTEM, Administrators and the named accounts may hold a right that writes, deletes or changes permissions.
    if ($Plan) { Say ("PLAN: check that only " + ((@("SYSTEM", "Administrators") + $Allowed) -join ', ') + " can write $Path"); return }
    $acl = Get-Acl -LiteralPath $Path
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($owner -ne 'S-1-5-32-544') { throw "$Path is owned by $owner, not Administrators" }
    $trusted = @('S-1-5-18', 'S-1-5-32-544') + $Allowed
    $bad = $acl.Access | Where-Object {
        $_.AccessControlType -eq 'Allow' -and
        ($_.FileSystemRights.ToString() -match 'Write|Modify|FullControl|Delete|ChangePermissions|TakeOwnership|CreateFiles|AppendData') -and
        ($_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $trusted)
    }
    if ($bad) { throw ("$Path has unexpected writers: " + (($bad | ForEach-Object { $_.IdentityReference.Value }) -join ', ')) }
}

function Set-CheckerCredential {
    # Store the runner's logon in thomas-checker's own credential store, so the checker can launch tests as the runner
    # (scripts\cage\checker_launch.py reads it) and the runner account cannot. The store is per-user, so cmdkey runs
    # as the checker through a one-shot task; the task is removed at once, with the password never left in a file.
    param(
        [Parameter(Mandatory)][string]$CheckerUser,
        [Parameter(Mandatory)][string]$CheckerPassword,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$RunnerAccount,
        [Parameter(Mandatory)][string]$RunnerPassword
    )
    $taskName = "ThomasCheckerCredentialOnce"
    $argument = '/c cmdkey /generic:"{0}" /user:"{1}" /pass:"{2}"' -f $Target, $RunnerAccount, $RunnerPassword
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $argument
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action `
            -User ("{0}\{1}" -f $env:COMPUTERNAME, $CheckerUser) -Password $CheckerPassword -RunLevel Limited | Out-Null
        Start-ScheduledTask -TaskName $taskName
        foreach ($i in 1..60) {
            Start-Sleep -Milliseconds 500
            $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
            if ($info -and $info.LastTaskResult -ne 267009 -and $info.LastRunTime.Year -gt 1999) { break }
        }
        if (-not $info -or $info.LastTaskResult -ne 0) {
            throw "could not store the runner credential as ${CheckerUser} (LastTaskResult=$($info.LastTaskResult))"
        }
    }
    finally {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
    }
}
