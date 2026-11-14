# Pin who may write Thomas's code, so the self-change promoter can refuse anyone new.
#
# Run elevated. It lists every principal with write access to Thomas's code, git
# config and hooks (scripts/cage/writer_audit.py --current), and pins that set as
# writers.allow in C:\ProgramData\ThomasPins -- the folder your unelevated
# processes cannot write or empty (see pin_folder.ps1). The promoter refuses every
# promotion while a writer outside this set exists, or while the pin is missing.
#
# Locking the folder also resets every pin already in it to inherit the folder's
# permissions, which repairs a pin an earlier run left unreadable.

param(
    [string]$RepoRoot = "",
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
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
    $python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
    $sids = @(& $python (Join-Path $scriptDir "writer_audit.py") --current $RepoRoot)
    if ($LASTEXITCODE -ne 0 -or $sids.Count -eq 0) { throw "could not list who can write Thomas's code" }
    $sids = $sids | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique

    Initialize-PinFolder -PinRoot $PinRoot
    $path = Write-PinFile -PinRoot $PinRoot -Name "writers.allow" -Value ($sids -join "`n")

    Say "== Writers of Thomas's code pinned ==" "Cyan"
    Say "  file: $path"
    foreach ($sid in $sids) {
        try { $name = (New-Object Security.Principal.SecurityIdentifier($sid)).Translate([Security.Principal.NTAccount]).Value }
        catch { $name = "(unresolved)" }
        Say "  $sid  $name"
    }
    # Checked on the ACL, not by reading: this runs elevated, and Administrators
    # can read a pin that ordinary processes -- Thomas included -- cannot.
    foreach ($pin in Get-ChildItem -LiteralPath $PinRoot -File) {
        $usersRead = (Get-Acl -LiteralPath $pin.FullName).Access | Where-Object {
            $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights.ToString() -match 'Read' -and
            $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-545'
        }
        if (-not $usersRead) { throw "pin $($pin.Name) is not readable by Users after locking the folder" }
        Say "  readable by Users: $($pin.Name)"
    }
    Say "RESULT: writers pinned" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
