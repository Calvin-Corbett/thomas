# Let the caged Thomas build in your projects. Run as you; no elevation (they are your folders).
#
# The caged server runs as the cage account but works in your ~/.thomas
# (caged_server.py sets THOMAS_OWNED_ROOT), so its Build finds the projects you
# already have. This gives that account exactly what Build needs and no more:
#   * Modify on the Build folders: projects, code_scratch, code_scratch_b, workspaces
#   * list-only on ~/.thomas itself, so it can find them (nothing inside inherits it)
#   * Modify on each project registered outside ~/.thomas (for example F:\DevHub),
#     except the Thomas repo, which stays behind the self-fix path and your approval
#   * git's safe.directory for those folders, for the cage account (through the caged
#     shell, trust_git_folders.py) and for you, so either account's git accepts a repo
#     the other one created
#
# Safe to run again. Rollback: icacls <folder> /remove thomas-agent.

param(
    [string]$RepoRoot = "",
    [string]$AgentUser = "thomas-agent",
    [string]$OwnedRoot = "",
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
if (-not $OwnedRoot) { $OwnedRoot = Join-Path $env:USERPROFILE ".thomas" }
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

function Grant([string]$Path, [string]$Rights) {
    # Exit codes decide, not stderr (see pin_folder.ps1).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & icacls $Path /grant "${AgentUser}:$Rights" /C /Q 2>$null | Out-Null; return $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
}

$failed = 0
try {
    $repo = (Resolve-Path $RepoRoot).Path.TrimEnd('\')
    $safe = New-Object System.Collections.Generic.List[string]

    if ((Grant $OwnedRoot "(RX)") -ne 0) { $failed++; Say "  FAILED list-only: $OwnedRoot" "Red" } else { Say "  list-only: $OwnedRoot" }
    foreach ($name in @("projects", "code_scratch", "code_scratch_b", "workspaces")) {
        $path = Join-Path $OwnedRoot $name
        if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
        if ((Grant $path "(OI)(CI)M") -ne 0) { $failed++; Say "  FAILED modify: $path" "Red"; continue }
        Say "  modify: $path"
        $pattern = ($path -replace '\\', '/')
        if ($name -in @("projects", "workspaces")) { $pattern += "/*" }
        $safe.Add($pattern) | Out-Null
    }

    $registry = Join-Path $RepoRoot ".thomas\evolve\agent\project_registry.json"
    $roots = @()
    if (Test-Path -LiteralPath $registry) {
        $rows = (Get-Content -LiteralPath $registry -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties.Value
        $roots = $rows | ForEach-Object { $_.project_root } | Where-Object { $_ } | Sort-Object -Unique
    }
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $full = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\')
        if ($full -eq $repo -or $full.StartsWith("$repo\", [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ($full.StartsWith("$OwnedRoot\", [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ((Grant $full "(OI)(CI)M") -ne 0) { $failed++; Say "  FAILED modify: $full" "Red"; continue }
        Say "  modify: $full"
        $safe.Add(($full -replace '\\', '/')) | Out-Null
    }

    # git: trust these folders for both accounts, adding only what is missing.
    $mine = @(& git config --global --get-all safe.directory 2>$null)
    foreach ($entry in $safe) { if ($mine -notcontains $entry) { & git config --global --add safe.directory $entry } }
    $out = & $python (Join-Path $scriptDir "trust_git_folders.py") @safe 2>&1
    Say "  git safe.directory set for you and for $AgentUser ($($safe.Count) folders): $out"

    if ($failed) { Say "RESULT: $failed folder(s) could not be shared - see above" "Red" }
    else { Say "RESULT: your Build projects are open to the caged Thomas" "Green" }
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
