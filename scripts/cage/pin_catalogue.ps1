<#
.SYNOPSIS
  Pin the approval cards' wording. Run elevated.

.DESCRIPTION
  Owner direction, 2026-09-22: "the only card you can use is the one that says
  what we want it to say. And it has an encryption thing that says yes or no,
  this is the actual one. So if you try to edit it or do anything, then it will
  it won't work."

  This records the SHA-256 of scripts/cage/card_catalogue.py in
  C:\ProgramData\ThomasPins\catalogue.sha256, a folder only Administrators can
  write or empty. thomas/tools/trusted_card.py refuses every PIN approval while
  the catalogue on disk does not match it, so editing a card's wording takes this
  script and a UAC prompt -- not a file write.

  The hash is computed here, from the bytes, never by asking the catalogue: a
  tampered file could report any hash it liked about itself.

  Run it again after an intended change to the cards.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cage\pin_catalogue.ps1
#>
[CmdletBinding()]
param(
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    [string]$RepoRoot = "",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptDir "pin_folder.ps1")
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
    $catalogue = Join-Path $RepoRoot "scripts\cage\card_catalogue.py"
    if (-not (Test-Path -LiteralPath $catalogue)) { throw "no catalogue at $catalogue" }

    $digest = Get-NormalizedSha256 -Path $catalogue
    Initialize-PinFolder -PinRoot $PinRoot
    $pin = Write-PinFile -PinRoot $PinRoot -Name "catalogue.sha256" -Value $digest

    Say "== Approval cards pinned ==" "Cyan"
    Say "  catalogue: $catalogue"
    Say "  pin:       $pin"
    Say "  sha256:    $digest"
    Say "RESULT: catalogue pinned" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
