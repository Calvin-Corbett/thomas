# The caged Thomas's own Claude sign-in (Task 2j). Run elevated, once; safe to run again.
#
# You chose it on a card: "Switch Thomas to Claude now", then "Yes, set it up".
# The cage gets a Claude sign-in of its own and never sees your own Claude folder.
#
#   1. nothing is changed if C:\ProgramData\ThomasCage, its claude\ or bin\ folder, or
#      anything inside those two folders, is a junction or link. An item the check
#      cannot read is named, with what to do. The folders on the way and the item are
#      checked again right before every delete, move and permission reset, never
#      remembered from the start
#   2. C:\ProgramData\ThomasCage\bin, owned by Administrators; SYSTEM and Administrators
#      full, you and the cage account read and run only (read back and checked). Your
#      claude.exe is copied there; the copy is checked byte for byte and must carry
#      Anthropic's valid Authenticode signature. Running this again updates it
#   3. the sign-in wrapper, scripts\cage\cage_claude_sign_in.ps1, copied beside it as
#      bin\sign-in.ps1, where only an administrator can change it
#   4. C:\ProgramData\ThomasCage\claude, the cage's Claude config folder. Inheritance
#      off; you, SYSTEM and Administrators full; the cage account Modify, because the
#      CLI refreshes its own sign-in there
#   5. the fence's allow-list pinned again, as enable_network_fence.ps1 does, when
#      scripts\cage\egress.allow changed. Every host line added or removed is printed
#      first; the proxy reads the pin for every connection
#   6. the sign-in step, only when the cage has no sign-in yet. It runs the wrapper in
#      a normal window. You never run the Claude CLI against the cage's folder: the
#      cage can write there, and the CLI applies settings it finds in its config folder
#      (measured: a settings file's env.BROWSER ran a program as the person signing in).
#      The wrapper signs in to a new folder only you can reach and moves the sign-in
#      across. That order is what protects you
#
# Nothing inside the cage's claude\ folder is deleted or changed here. The cage can
# write there, and code running elevated never deletes through a folder the cage can
# write. What keeps your sign-in safe is the order in step 6, not any clean-up.
#
# This script runs icacls as C:\Windows\System32\icacls.exe, never found on PATH: a
# folder any signed-in account can write can sit on PATH. (pin_folder.ps1, which step
# 5 uses, still finds icacls and takeown on PATH.)
#
# Nothing is started or restarted here. The caged server finds the folder at its next
# start (scripts\cage\caged_server.py).
#
# Rollback (elevated): Remove-Item -Recurse C:\ProgramData\ThomasCage\claude and
# C:\ProgramData\ThomasCage\bin; to take the allow-list line back out, remove it from
# scripts\cage\egress.allow and run this script or enable_network_fence.ps1 again.

param(
    [string]$RepoRoot = "",
    [string]$AgentUser = "thomas-agent",
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    [string]$ClaudeExe = "",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
if (-not $ClaudeExe) { $ClaudeExe = Join-Path $env:USERPROFILE ".local\bin\claude.exe" }
. (Join-Path $scriptDir "pin_folder.ps1")

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
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

function Test-Link([string]$Path) {
    return [bool]((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Assert-NotLink([string[]]$Paths) {
    # Right before a delete, a move or a reset: each path that exists now is not a
    # junction or link now. GetAttributes reads a link itself, even a dangling one.
    foreach ($path in $Paths) {
        try { $attributes = [System.IO.File]::GetAttributes($path) }
        catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { continue }
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$path is a junction or link; stopping" }
    }
}

function Assert-NoLinkInside([string]$Dir) {
    # Every item under $Dir. What this account cannot read is named, because the check
    # cannot see past it, with the way on that deletes nothing.
    $unreadable = $null
    $items = @(Get-ChildItem -LiteralPath $Dir -Force -Recurse -ErrorAction SilentlyContinue -ErrorVariable unreadable)
    if ($unreadable.Count) {
        $names = @($unreadable | ForEach-Object { if ($_.TargetObject) { [string]$_.TargetObject } else { $_.Exception.Message } })
        $aside = (Split-Path -Leaf $Dir) + ".unreadable-" + (Get-Date -Format "yyyyMMddHHmmss")
        throw ("the link check cannot read " + ($names -join ", ") + ", so it cannot tell whether $Dir holds a junction or link; nothing was changed. " +
            "Move the folder aside with Rename-Item -LiteralPath `"$Dir`" -NewName `"$aside`", then run this again. " +
            "Moving claude aside takes the cage's Claude sign-in with it; sign in again afterwards with bin\sign-in.ps1.")
    }
    $links = @($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($links.Count) { throw ("links inside $Dir, nothing was changed: " + (($links | ForEach-Object { $_.FullName }) -join ', ')) }
}

function Assert-FolderAcl([string]$Path, [string[]]$Sids, [string]$ReadOnlySid) {
    # Read back what icacls set: inheritance off, nobody else, and $ReadOnlySid (when
    # given) at most read-and-run.
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) { throw "$Path still inherits permissions" }
    $readRun = [int]([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Synchronize)
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne 'Allow') { continue }
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($sid -notin $Sids) { throw "$Path has an unexpected entry: $($rule.IdentityReference.Value)" }
        if ($ReadOnlySid -and $sid -eq $ReadOnlySid -and ([int]$rule.FileSystemRights -band -bnot $readRun)) {
            throw "$Path gives $($rule.IdentityReference.Value) more than read and run: $($rule.FileSystemRights)"
        }
    }
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "not elevated"
    }
    $ownerSid = $identity.User.Value
    $agentSid = (Get-LocalUser -Name $AgentUser).SID.Value
    if (-not (Test-Path -LiteralPath $CageRoot -PathType Container)) { throw "$CageRoot is missing: set the cage up first (enable_cage.ps1)" }
    if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) { throw "no icacls at $icacls" }
    if (-not (Test-Path -LiteralPath $ClaudeExe -PathType Leaf)) { throw "no Claude CLI at $ClaudeExe (pass -ClaudeExe <path to claude.exe>)" }
    $wrapperSource = Join-Path $scriptDir "cage_claude_sign_in.ps1"
    if (-not (Test-Path -LiteralPath $wrapperSource -PathType Leaf)) { throw "no sign-in wrapper at $wrapperSource" }

    $configDir = Join-Path $CageRoot "claude"
    $binDir = Join-Path $CageRoot "bin"
    $target = Join-Path $binDir "claude.exe"
    $wrapper = Join-Path $binDir "sign-in.ps1"
    $credentials = Join-Path $configDir ".credentials.json"

    # 1. Before anything else: no junctions or links on the way in or inside.
    if (Test-Link $CageRoot) { throw "$CageRoot is a junction or link; nothing was changed" }
    foreach ($dir in @($configDir, $binDir)) {
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        if (Test-Link $dir) { throw "$dir is a junction or link; nothing was changed" }
        Assert-NoLinkInside $dir
    }
    $configIsNew = -not (Test-Path -LiteralPath $configDir)
    foreach ($dir in @($configDir, $binDir)) {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    }

    # 2. The CLI's folder, then the CLI. The folder is set first, so what is copied in
    # inherits read-and-run for the cage account and nothing more. A running copy cannot
    # be overwritten, but it can be renamed out of the way.
    Invoke-Icacls @($binDir, "/setowner", "*S-1-5-32-544")
    Invoke-Icacls @($binDir, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", "*${ownerSid}:(OI)(CI)RX", "*${agentSid}:(OI)(CI)RX")
    Assert-FolderAcl $binDir @('S-1-5-18', 'S-1-5-32-544', $ownerSid, $agentSid) $agentSid
    $binOwner = (Get-Acl -LiteralPath $binDir).GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($binOwner -ne 'S-1-5-32-544') { throw "$binDir is owned by $binOwner, not Administrators" }
    foreach ($leftover in @(Get-ChildItem -LiteralPath $binDir -Force -Filter "claude.exe.new-*")) {
        Assert-NotLink @($CageRoot, $binDir, $leftover.FullName)
        Remove-Item -LiteralPath $leftover.FullName -Force -ErrorAction SilentlyContinue
    }
    $staged = Join-Path $binDir ("claude.exe.new-" + [guid]::NewGuid().ToString("N"))
    Copy-Item -LiteralPath $ClaudeExe -Destination $staged
    $hash = (Get-FileHash -LiteralPath $ClaudeExe -Algorithm SHA256).Hash
    $signature = Get-AuthenticodeSignature -LiteralPath $staged
    $signed = $signature.Status -eq 'Valid' -and $signature.SignerCertificate.Subject.StartsWith('CN="Anthropic, PBC"')
    if (((Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash -ne $hash) -or -not $signed) {
        Assert-NotLink @($CageRoot, $binDir, $staged)
        Remove-Item -LiteralPath $staged -Force
        throw "the copy of $ClaudeExe is not an Anthropic-signed match of it (signature: $($signature.Status)); nothing was replaced"
    }
    $version = (Get-Item -LiteralPath $staged).VersionInfo.ProductVersion
    if (Test-Path -LiteralPath $target) {
        Assert-NotLink @($CageRoot, $binDir, $target)
        Move-Item -LiteralPath $target -Destination ($target + ".old-" + (Get-Date -Format "yyyyMMddHHmmss"))
    }
    Assert-NotLink @($CageRoot, $binDir, $staged, $target)
    Move-Item -LiteralPath $staged -Destination $target
    Assert-NotLink @($CageRoot, $binDir, $target)
    Invoke-Icacls @($target, "/reset")
    foreach ($old in @(Get-ChildItem -LiteralPath $binDir -Force -Filter "claude.exe.old-*")) {
        Assert-NotLink @($CageRoot, $binDir, $old.FullName)
        Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
    }
    Say "  CLI copied: $target (version $version, sha256 $($hash.Substring(0, 12))..., signed by Anthropic, PBC; $AgentUser read and run only)"

    # 3. The sign-in wrapper, where only an administrator can change it.
    Assert-NotLink @($CageRoot, $binDir, $wrapper)
    Copy-Item -LiteralPath $wrapperSource -Destination $wrapper -Force
    Assert-NotLink @($CageRoot, $binDir, $wrapper)
    Invoke-Icacls @($wrapper, "/reset")
    if ((Get-FileHash -LiteralPath $wrapper).Hash -ne (Get-FileHash -LiteralPath $wrapperSource).Hash) { throw "the copy of $wrapperSource does not match it" }
    Say "  sign-in wrapper: $wrapper ($AgentUser read and run only)"

    # 4. The cage's config folder. Its permissions are set only while it is new and
    # empty; once the cage can write inside it, it is only checked, so nothing elevated
    # is ever pushed down into what the cage wrote there.
    if ($configIsNew) {
        Invoke-Icacls @($configDir, "/inheritance:r", "/grant:r", "*${ownerSid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", "*${agentSid}:(OI)(CI)M")
    }
    Assert-FolderAcl $configDir @($ownerSid, $agentSid, 'S-1-5-18', 'S-1-5-32-544') ""
    $cageRule = @((Get-Acl -LiteralPath $configDir).Access | Where-Object {
            $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $agentSid
        })
    if (-not $cageRule.Count) { throw "$configDir does not give $AgentUser access; remove the folder and run this again" }
    Say "  config folder: $configDir (you, SYSTEM, Administrators full; $AgentUser modify; nothing inside it touched)"

    # 5. The allow-list, only when the repo copy changed and a fence is pinned. You see
    # every host line that changes before it is pinned.
    $allow = [System.IO.File]::ReadAllText((Join-Path $scriptDir "egress.allow"))
    $pinned = Join-Path $PinRoot "egress.allow"
    if (-not (Test-Path -LiteralPath $pinned)) {
        Say "  no network fence pinned at $pinned; nothing to update (enable_network_fence.ps1 pins it)"
    }
    elseif (([System.IO.File]::ReadAllText($pinned) -replace "`r`n", "`n") -eq ($allow -replace "`r`n", "`n")) {
        Say "  allow-list pin already current: $pinned"
    }
    else {
        $hostsOf = { param($text) @($text -split "`r?`n" | ForEach-Object { ($_ -split '#', 2)[0].Trim().ToLower() } | Where-Object { $_ }) }
        $before = & $hostsOf ([System.IO.File]::ReadAllText($pinned))
        $after = & $hostsOf $allow
        foreach ($name in $after) { if ($name -notin $before) { Say "  allow-list adds: $name" "Yellow" } }
        foreach ($name in $before) { if ($name -notin $after) { Say "  allow-list removes: $name" "Yellow" } }
        Initialize-PinFolder -PinRoot $PinRoot
        $pinPath = Write-PinFile -PinRoot $PinRoot -Name "egress.allow" -Value $allow
        Say "  allow-list pinned again: $pinPath"
    }

    # 6. Your step, only when there is no sign-in yet. A later sign-in is the same step.
    $step = 'powershell -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $wrapper
    if (Test-Path -LiteralPath $credentials) {
        Say "RESULT: CLI updated; no sign-in needed" "Green"
        Say "If the cage's sign-in ever has to be renewed, run this in a new, normal (not elevated) PowerShell window:"
        Say "  $step"
    }
    else {
        Say "RESULT: ready for your sign-in" "Green"
        Say "Close this window. Open a new, normal (not elevated) PowerShell window and run:" "Cyan"
        Say "  $step" "Cyan"
    }
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
