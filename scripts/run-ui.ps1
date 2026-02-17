param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8899,
  [switch]$AutoPort,
  [switch]$NoBrowser,
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
    & $Exe @Args
    return $LASTEXITCODE
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

function Ensure-Installed {
  if ($NoInstall) { return }

  # Install only if missing deps (keeps repeat runs fast).
  $probe = Invoke-NativeQuiet $VenvPy @("-c", "import aiohttp, httpx")
  if ($probe -ne 0) {
    Write-Host "[thomas] Installing dependencies (editable) ..."
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "--upgrade", "pip")
    if ($code -ne 0) { throw "[thomas] pip upgrade failed (exit $code)" }
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server]")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
    return
  }

  # Ensure the package entrypoints are present (optional but convenient).
  $show = Invoke-NativeQuiet $VenvPy @("-m", "pip", "show", "thomas")
  if ($show -ne 0) {
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server]")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
  }
}

function Find-FreePort([int]$Preferred) {
  for ($p = $Preferred; $p -le ($Preferred + 25); $p++) {
    $inUse = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not $inUse) { return $p }
  }
  return 0
}

Ensure-Installed

function Stop-ThomasServerOnPort([int]$P) {
  $listeners = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
  if (-not $listeners) { return $false }

  foreach ($l in $listeners) {
    # Avoid PowerShell's built-in $PID (read-only) which is case-insensitive.
    $owningPid = [int]$l.OwningProcess
    if ($owningPid -le 0) { continue }

    $cmd = $null
    try {
      $cmd = (Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $owningPid) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)
    } catch { }

    if ($cmd -and $cmd -match '(?i)(\\b-m\\s+thomas\\s+serve\\b|\\bthomas(\\.exe)?\\s+serve\\b|\\b-m\\s+thomas\\.server\\b)') {
      Write-Host ("[thomas] Port {0} is in use by an existing Thomas server (pid {1}); stopping it..." -f $P, $owningPid)
      try { Stop-Process -Id $owningPid -Force -ErrorAction SilentlyContinue } catch { }
      Start-Sleep -Milliseconds 400
      return $true
    }
  }

  return $false
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

function Ensure-OllamaRunning {
  $oll = Get-Command ollama -ErrorAction SilentlyContinue
  if (-not $oll) {
    Write-Host "[thomas] NOTE: Ollama not found. If your local model is Ollama, install it from https://ollama.com"
    return
  }

  $listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
  if ($listening) { return }

  Write-Host "[thomas] Starting Ollama (for local model endpoint on :11434)..."
  try {
    Start-Process -FilePath $oll.Source -ArgumentList @("serve") -WindowStyle Minimized | Out-Null
  } catch {
    Write-Host "[thomas] NOTE: Failed to auto-start Ollama. You can start it manually with: ollama serve"
    return
  }

  Start-Sleep -Milliseconds 800
}

if (Uses-OllamaLocal) {
  Ensure-OllamaRunning
}

# Prefer a stable URL. If the chosen port is already taken by another Thomas server, stop it.
Stop-ThomasServerOnPort $Port | Out-Null

$FreePort = Find-FreePort $Port
if ($FreePort -eq 0) {
  Write-Host "[thomas] ERROR: No free port found in range $Port..$($Port + 25)."
  exit 2
}

if ($FreePort -ne $Port) {
  if (-not $AutoPort) {
    Write-Host "[thomas] ERROR: Port $Port is busy."
    Write-Host "[thomas] Close the process on that port, or rerun with -AutoPort."
    exit 2
  }
  Write-Host "[thomas] Port $Port is busy; using $FreePort because -AutoPort is enabled."
  $Port = $FreePort
}

$Url = "http://$BindHost`:$Port/"
Write-Host ""
Write-Host "[thomas] UI: $Url"
Write-Host "[thomas] If this stays on \"ready\" but won't answer, check thomas.toml model endpoints."
Write-Host ""

if (-not $NoBrowser) {
  try { Start-Process $Url | Out-Null } catch { }
}

& $VenvPy -m thomas.server --host $BindHost --port $Port 2>&1
