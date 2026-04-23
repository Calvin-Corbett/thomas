param(
  [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Invoke-NativeQuiet {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  # In Windows PowerShell 5.1, redirecting stderr on a native command can emit
  # a NativeCommandError which (with $ErrorActionPreference="Stop") terminates
  # the script. Temporarily relax error handling for these probes.
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Exe @Args 2>$null | Out-Null
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Exe @Args 2>&1 | Out-Host
    return [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Find-SystemPython {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "python"; Path = $cmd.Source } }
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "py"; Path = $cmd.Source } }
  return $null
}

$SysPy = Find-SystemPython
if (-not $SysPy) {
  Write-Host "[thomas] ERROR: Python not found in PATH."
  Write-Host "[thomas] Install Python 3.10+ and try again."
  exit 2
}

$VenvPy = Join-Path $Root ".venv\\Scripts\\python.exe"
if (-not (Test-Path $VenvPy)) {
  Write-Host "[thomas] Creating venv in .venv..."
  if ($SysPy.Kind -eq "py") {
    & $SysPy.Path -3 -m venv .venv
  } else {
    & $SysPy.Path -m venv .venv
  }
  if (-not (Test-Path $VenvPy)) {
    Write-Host "[thomas] ERROR: venv creation failed."
    exit 2
  }
}

if (-not $NoInstall) {
  $probe = Invoke-NativeQuiet $VenvPy @("-c", "import click, httpx")
  if ($probe -ne 0) {
    Write-Host "[thomas] Installing dependencies (editable) ..."
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "--upgrade", "pip")
    if ($code -ne 0) { throw "[thomas] pip upgrade failed (exit $code)" }
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[repl,server]")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
  }
}

function Uses-OllamaLocal {
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return $false }
  $t = Get-Content $cfgPath -Raw
  if ($t -match 'default_model\\s*=\\s*\"local\"' -and $t -match 'base_url\\s*=\\s*\"http://(localhost|127\\.0\\.0\\.1):11434') {
    return $true
  }
  return $false
}

function Get-DefaultModelName {
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return "" }
  $t = Get-Content $cfgPath -Raw
  $m = [regex]::Match($t, '(?m)^\\s*default_model\\s*=\\s*\"(?<value>[^\"]+)\"')
  if (-not $m.Success) { return "" }
  return $m.Groups["value"].Value.Trim().ToLowerInvariant()
}

function Get-ProfileApiKeyFromToml {
  param([string]$Profile)
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return "" }
  $t = Get-Content $cfgPath -Raw
  $escaped = [regex]::Escape($Profile)
  $section = [regex]::Match($t, "(?ms)^\\[models\\.$escaped\\]\\s*(?<body>.*?)(?=^\\[|\\z)")
  if (-not $section.Success) { return "" }
  $api = [regex]::Match($section.Groups["body"].Value, '(?m)^\\s*api_key\\s*=\\s*\"(?<key>[^\"]*)\"')
  if (-not $api.Success) { return "" }
  return $api.Groups["key"].Value.Trim()
}

function Show-DefaultModelWarning {
  $defaultModel = Get-DefaultModelName
  if (-not $defaultModel) { return }

  if ($defaultModel -in @("openai", "anthropic")) {
    $envName = "THOMAS_MODELS_" + $defaultModel.ToUpperInvariant() + "_API_KEY"
    $envValue = [Environment]::GetEnvironmentVariable($envName, "Process")
    if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "User") }
    if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "Machine") }
    $cfgKey = Get-ProfileApiKeyFromToml -Profile $defaultModel
    if (-not $envValue -and -not $cfgKey) {
      Write-Host ("[thomas] WARNING: default_model '{0}' has no API key configured." -f $defaultModel)
      Write-Host ("[thomas] Run setup.cmd or set {0} before chatting." -f $envName)
    }
  }
}

function Ensure-OllamaRunning {
  $oll = Get-Command ollama -ErrorAction SilentlyContinue
  if (-not $oll) { return }
  $listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
  if ($listening) { return }
  Write-Host "[thomas] Starting Ollama (for local model endpoint on :11434)..."
  try { Start-Process -FilePath $oll.Source -ArgumentList @("serve") -WindowStyle Minimized | Out-Null } catch { return }
  Start-Sleep -Milliseconds 800
}

if (Uses-OllamaLocal) {
  Ensure-OllamaRunning
}
Show-DefaultModelWarning

& $VenvPy -m thomas repl
