param(
  [switch]$SkipInstall,
  [switch]$SkipDoctor,
  [switch]$WithTestDeps,
  [ValidateSet("auto", "local", "codex", "openai", "anthropic")]
  [string]$Profile = "auto",
  [switch]$Easy,
  [switch]$AutoInstallTools,
  [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$SetupScript = Join-Path $PSScriptRoot "setup.ps1"
if (-not (Test-Path $SetupScript)) {
  Write-Host "[thomas] ERROR: missing setup script: $SetupScript"
  exit 2
}

& $SetupScript @PSBoundParameters
exit $LASTEXITCODE
