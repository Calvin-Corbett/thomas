# Sign the caged Thomas in to your Claude plan (Task 2j). Run in a normal PowerShell
# window, never an elevated one; this script refuses to run elevated.
#
# enable_cage_claude.ps1 copies this file to C:\ProgramData\ThomasCage\bin\sign-in.ps1,
# where only an administrator can change it. Run that copy:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\ThomasCage\bin\sign-in.ps1"
#
# Why this order. The cage account can write its own Claude folder,
# C:\ProgramData\ThomasCage\claude, and the Claude CLI applies the settings it finds
# in its config folder. Measured on 2026-09-24: a settings file's env.BROWSER made
# `claude auth login` run a program as the person signing in. So you never run the CLI
# against the cage's folder:
#   1. a new folder that only you can reach, under your LOCALAPPDATA\Temp
#   2. claude.exe auth login --claudeai in a child process: only that process's
#      environment points CLAUDE_CONFIG_DIR at the new folder, so this window keeps
#      no trace of it
#   3. the new .credentials.json is moved into the cage's folder (a move runs nothing).
#      Its permissions are reset to the cage folder's and then checked from its ACL.
#      Its contents are never read, printed or copied. The cage can write in that
#      folder, so right before each delete, the move and the reset, ThomasCage, claude\
#      and the file are checked again for junctions and links
#   4. the new folder is deleted, whatever happened
#
# icacls is run as C:\Windows\System32\icacls.exe, never found on PATH: a folder any
# signed-in account can write can sit on PATH.
#
# Run it again whenever the cage's sign-in has to be renewed; it replaces the old one.

param(
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$AgentUser = "thomas-agent"
)

$ErrorActionPreference = "Stop"

function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
}

function Assert-NotLink([string[]]$Paths) {
    # Checked when it is used, never remembered: each path that exists now is not a
    # junction or link now. GetAttributes reads a link itself, even a dangling one.
    foreach ($path in $Paths) {
        try { $attributes = [System.IO.File]::GetAttributes($path) }
        catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { continue }
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$path is a junction or link; stopping" }
    }
}

$icacls = "C:\Windows\System32\icacls.exe"

function Invoke-Icacls([string[]]$IcaclsArgs) {
    # Exit codes decide, not stderr (see pin_folder.ps1).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $icacls @IcaclsArgs /Q 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw ("icacls returned $LASTEXITCODE for: " + ($IcaclsArgs -join ' ')) }
    }
    finally { $ErrorActionPreference = $previous }
}

function Get-AllowedSids([string]$Path) {
    (Get-Acl -LiteralPath $Path).Access | Where-Object { $_.AccessControlType -eq 'Allow' } |
        ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
}

$temp = $null
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ((New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "this window is elevated; open a normal PowerShell window and run it there"
    }
    $mySid = $identity.User.Value
    $agentSid = (New-Object Security.Principal.NTAccount($AgentUser)).Translate([Security.Principal.SecurityIdentifier]).Value
    $configDir = Join-Path $CageRoot "claude"
    $binDir = Join-Path $CageRoot "bin"
    $claude = Join-Path $binDir "claude.exe"
    $destination = Join-Path $configDir ".credentials.json"
    if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) { throw "no icacls at $icacls" }
    foreach ($path in @($CageRoot, $configDir, $binDir, $claude)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "$path is missing: run enable_cage_claude.ps1 (elevated) first" }
        Assert-NotLink $path
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $claude
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate.Subject.StartsWith('CN="Anthropic, PBC"')) {
        throw "$claude is not signed by Anthropic ($($signature.Status)); stopping"
    }

    # 1. A folder only you can reach.
    $temp = Join-Path $env:LOCALAPPDATA ("Temp\thomas-cage-signin-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temp | Out-Null
    Invoke-Icacls @($temp, "/inheritance:r", "/grant:r", "*${mySid}:(OI)(CI)F")
    $others = @(Get-AllowedSids $temp | Where-Object { $_ -ne $mySid })
    if ($others.Count -or -not (Get-Acl -LiteralPath $temp).AreAccessRulesProtected) {
        throw "$temp could not be made yours alone"
    }

    # 2. The sign-in, in a child process. Only its environment names the new folder.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $claude
    $start.Arguments = "auth login --claudeai"
    $start.UseShellExecute = $false
    $start.WorkingDirectory = $temp
    $start.EnvironmentVariables["CLAUDE_CONFIG_DIR"] = $temp
    Say "Your browser opens: sign in with the Claude account that has your plan." "Cyan"
    $process = [System.Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "the sign-in did not finish (claude exited $($process.ExitCode)); nothing was changed" }
    $fresh = Join-Path $temp ".credentials.json"
    if (-not (Test-Path -LiteralPath $fresh -PathType Leaf)) { throw "the sign-in left no credentials; nothing was changed" }

    # 3. Into the cage's folder. Nothing already there is trusted: a link stops this, an
    # old sign-in is deleted, and File.Move refuses to land on anything that appears.
    # The cage can write in claude\, so the folders on the way and the file are checked
    # again right before each step, not remembered from the start.
    if (Test-Path -LiteralPath $destination) {
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw "$destination is not a file; stopping" }
        Assert-NotLink @($CageRoot, $configDir, $destination)
        [System.IO.File]::Delete($destination)
    }
    Assert-NotLink @($CageRoot, $configDir, $destination)
    [System.IO.File]::Move($fresh, $destination)
    Assert-NotLink @($CageRoot, $configDir, $destination)
    Invoke-Icacls @($destination, "/reset")
    $expected = @($mySid, $agentSid, 'S-1-5-18', 'S-1-5-32-544')
    $unexpected = @(Get-AllowedSids $destination | Where-Object { $_ -notin $expected })
    $modify = [Security.AccessControl.FileSystemRights]::Modify
    $cage = @((Get-Acl -LiteralPath $destination).Access | Where-Object {
            $_.AccessControlType -eq 'Allow' -and
            $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $agentSid -and
            (($_.FileSystemRights -band $modify) -eq $modify)
        })
    if ($unexpected.Count -or -not $cage.Count) {
        Assert-NotLink @($CageRoot, $configDir, $destination)
        [System.IO.File]::Delete($destination)
        throw "$destination did not get the cage folder's permissions, so it was deleted; run this again"
    }
    Say "RESULT: the caged Thomas is signed in to Claude" "Green"
    Say "  $destination : $AgentUser may read and change it (checked from its permissions; its contents were not read)"
    Say "  The caged server uses it from its next start."
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    # Directory.Delete removes a link, never what it points to.
    if ($temp -and (Test-Path -LiteralPath $temp)) {
        try { [System.IO.Directory]::Delete($temp, $true) } catch { Say "  could not delete $temp; delete it yourself" "Yellow" }
    }
}
