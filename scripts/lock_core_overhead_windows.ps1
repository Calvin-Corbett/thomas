[CmdletBinding()]
param(
  [string]$ManifestPath = "",
  [string]$Principal = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
  throw "Run this script from an elevated PowerShell window (native UAC prompt)."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ManifestPath) {
  $ManifestPath = Join-Path $repoRoot "docs/core_overhead_manifest.json"
}
if (-not (Test-Path $ManifestPath)) {
  throw "Manifest not found: $ManifestPath"
}

if (-not $Principal) {
  $Principal = "$env:USERDOMAIN\$env:USERNAME"
}

$manifest = Get-Content -Path $ManifestPath -Raw | ConvertFrom-Json
$files = @($manifest.protected_files)
if ($files.Count -eq 0) {
  throw "Manifest has no protected_files."
}

foreach ($rel in $files) {
  $relPath = [string]$rel
  $full = Join-Path $repoRoot $relPath
  if (-not (Test-Path $full)) {
    Write-Warning "Skip missing file: $relPath"
    continue
  }

  # Lock: current principal gets read+execute only; admins/system keep full control.
  & icacls $full /inheritance:r /grant:r "SYSTEM:(F)" "Administrators:(F)" "$Principal:(RX)" | Out-Null
}

Write-Host "Core overhead locked for principal: $Principal"
Write-Host "Protected files are now read-only for that principal."
