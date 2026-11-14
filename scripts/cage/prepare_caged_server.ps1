# Give the cage account what a caged Thomas server needs, and nothing more. Runs as
# you, no elevation: every folder here is one you own or hold full control of.
#
#   desk\requests   thomas-agent may file approval requests      (Modify)
#   desk\answers    thomas-agent may read your answers, never write (Read)
#   inbox           thomas-agent may hand a self-fix in (Modify: the hand-off
#                   writes a staging folder and renames it into place)
#   <you>\.codex    shared with thomas-agent, as you chose, so the caged server
#                   uses your Codex login and a token refresh never logs the other out
#
# Each grant is checked afterwards from the cage account's side, through the caged
# shell itself, rather than trusted because icacls returned 0.

param(
    [string]$CageRoot = "C:\ProgramData\ThomasCage",
    [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
    [string]$AgentUser = "thomas-agent",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

function Grant([string]$Path, [string]$Rights) {
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path -Force | Out-Null }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & icacls $Path /grant "${AgentUser}:(OI)(CI)$Rights" /Q 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls returned $LASTEXITCODE for $Path" }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    Say "  $AgentUser $Rights on $Path"
}

try {
    Grant (Join-Path $CageRoot "desk\requests") "M"
    Grant (Join-Path $CageRoot "desk\answers") "RX"
    Grant (Join-Path $CageRoot "inbox") "M"
    if (-not (Test-Path -LiteralPath $CodexHome)) { throw "no Codex folder at $CodexHome" }
    Grant $CodexHome "M"
    Say "RESULT: prepared" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
