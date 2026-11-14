<#
.SYNOPSIS
  Pin the cage posture where Thomas cannot change it. Run elevated, once, after
  the runner is proven to answer.

.DESCRIPTION
  Owner direction, 2026-09-22: "It is not a rule about what you should or not
  do. It's literally a wall that you can't go through no matter what you try."

  thomas.toml cannot hold this setting honestly. The server runs as you, so it
  can rewrite any repo file at any time; the protected-files gate only sees
  that afterwards, in a diff. This writes the posture to the cage root instead
  and takes write access away from everyone but an administrator:

    SYSTEM          full
    Administrators  full      <- you, after a UAC prompt
    Users           read      <- the server process, the caged account, Thomas

  An unelevated process running as you cannot write it, because UAC hands that
  process a token in which Administrators is deny-only. So nothing Thomas runs
  can lower the posture, and you can raise or drop it whenever you like.

  thomas/tools/cage_shell.py reads this as a FLOOR: the environment and the
  config may ask for more cage than is pinned, never less.

.PARAMETER Posture
  required  the cage or nothing -- a shell refuses when the runner is silent
  auto      caged when the runner answers, local when it does not
  off       never use the cage

.PARAMETER Remove
  Delete the pin, returning control to the environment and the config.

.EXAMPLE
  # Only after a real command has come back from the cage.
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cage\pin_posture.ps1 -Posture required
#>
[CmdletBinding()]
param(
    [ValidateSet("required", "auto", "off")]
    [string]$Posture = "required",
    # Pins live here, not in the cage root. See pin_folder.ps1 for why.
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    # Where the posture used to be pinned. Its pin is removed on every run: the
    # reader keeps honouring it (strictest wins), so a stale "required" left
    # there would silently defeat any later attempt to lower the posture.
    [string]$LegacyRoot = "C:\ProgramData\ThomasCage",
    [switch]$Remove,
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptDir "pin_folder.ps1")

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

    $path = Join-Path $PinRoot "posture"
    $legacy = Join-Path $LegacyRoot "posture"

    if ($Remove) {
        foreach ($p in @($path, $legacy)) { if (Test-Path -LiteralPath $p) { [System.IO.File]::Delete($p) } }
        Say "RESULT: pin removed" "Yellow"
        return
    }

    Initialize-PinFolder -PinRoot $PinRoot
    $path = Write-PinFile -PinRoot $PinRoot -Name "posture" -Value $Posture
    if (Test-Path -LiteralPath $legacy) {
        [System.IO.File]::Delete($legacy)
        Say "  removed the old pin at $legacy"
    }

    Say "== Cage posture pinned ==" "Cyan"
    Say "  file:    $path"
    Say "  posture: $Posture"
    $writers = (Get-Acl -LiteralPath $PinRoot).Access |
        Where-Object { $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights.ToString() -match 'Write|Modify|FullControl|Delete' } |
        ForEach-Object { $_.IdentityReference.Value }
    Say ("  folder writable or emptiable by: " + ($writers -join ", "))
    Say "RESULT: posture pinned to $Posture" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
