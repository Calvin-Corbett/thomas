param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8899,
  [switch]$AutoPort,
  [switch]$StrictPort,
  [switch]$NoBrowser,
  [switch]$NoInstall,
  [switch]$NoTray,
  [switch]$Headless
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

function Get-CommandPathAny {
  param([string[]]$Names)
  foreach ($n in $Names) {
    $cmd = Get-Command $n -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
      return [string]$cmd.Source
    }
  }
  return ""
}

function Test-WingetAvailable {
  $winget = Get-CommandPathAny @("winget", "winget.exe")
  return -not [string]::IsNullOrWhiteSpace($winget)
}

function Install-WithWinget {
  param(
    [Parameter(Mandatory = $true)][string]$PackageId,
    [Parameter(Mandatory = $true)][string]$DisplayName
  )

  if (-not (Test-WingetAvailable)) {
    Write-Host ("[thomas] winget not found. Cannot auto-install {0}." -f $DisplayName)
    return $false
  }

  Write-Host ("[thomas] Installing {0} via winget..." -f $DisplayName)
  $wingetExe = Get-CommandPathAny @("winget", "winget.exe")
  $code = Invoke-Native $wingetExe @(
    "install",
    "--id", $PackageId,
    "--exact",
    "--silent",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  )
  if ($code -ne 0) {
    Write-Host ("[thomas] winget install failed for {0} (exit {1})." -f $DisplayName, $code)
    return $false
  }

  return $true
}

function Ensure-SystemPython {
  $found = Find-SystemPython
  if ($found) {
    return $found
  }

  Write-Host "[thomas] Python not found. Attempting automatic install..."
  $installed = Install-WithWinget -PackageId "Python.Python.3.11" -DisplayName "Python 3.11"
  if (-not $installed) {
    $installed = Install-WithWinget -PackageId "Python.Python.3.12" -DisplayName "Python 3.12"
  }
  if (-not $installed) {
    return $null
  }

  # Refresh process PATH from user/machine scopes so newly installed binaries
  # are visible without requiring a new shell.
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $combined = @($env:Path, $userPath, $machinePath) -join ";"
  $parts = $combined -split ";" | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
  $env:Path = ($parts -join ";")

  $redetected = Find-SystemPython
  if ($redetected) {
    return $redetected
  }

  $fallbacks = @(
    (Join-Path $env:LocalAppData "Programs\\Python\\Python312\\python.exe"),
    (Join-Path $env:LocalAppData "Programs\\Python\\Python311\\python.exe"),
    (Join-Path $env:LocalAppData "Programs\\Python\\Python310\\python.exe"),
    "C:\\Program Files\\Python312\\python.exe",
    "C:\\Program Files\\Python311\\python.exe",
    "C:\\Program Files\\Python310\\python.exe"
  )
  foreach ($candidate in $fallbacks) {
    if (Test-Path $candidate) {
      return @{ Kind = "python"; Path = $candidate }
    }
  }

  return $null
}

$SysPy = Ensure-SystemPython
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

function Test-ThomasHttpOnPort([int]$P) {
  try {
    $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/models" -f $P) -UseBasicParsing -TimeoutSec 2 -Method Get -ErrorAction Stop
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
  } catch {
    return $false
  }
}

function Invoke-BootDoctor {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [int]$DiagPort = 8899
  )

  Write-Host ""
  Write-Host ("[thomas] Boot Doctor: {0}" -f $Reason)

  $diagDir = Join-Path $Root "runtime\\boot_doctor"
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $report = Join-Path $diagDir ("boot_doctor_{0}.txt" -f $stamp)

  try {
    & $VenvPy -m thomas boot-doctor --port $DiagPort --reason $Reason --report $report
    if ($LASTEXITCODE -ne 0) {
      throw ("boot-doctor exit code {0}" -f $LASTEXITCODE)
    }
  } catch {
    Set-Content -Path $report -Value ("Boot Doctor failed: {0}" -f $_.Exception.Message) -Encoding UTF8
  }

  Write-Host ("[thomas] Boot Doctor report: {0}" -f $report)
  try { Start-Process notepad.exe $report | Out-Null } catch { }
}

function Get-ThomasListenersOnPort([int]$P) {
  $hits = @()
  $listeners = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
  if (-not $listeners) { return $hits }
  foreach ($l in $listeners) {
    $owningPid = [int]$l.OwningProcess
    if ($owningPid -le 0) { continue }
    $cmd = $null
    try {
      $cmd = (Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $owningPid) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)
    } catch { }
    if ($cmd -and $cmd -match '(?i)(-m\s+thomas(\.server)?(\s+serve)?\b|-m\s+thomas\.tray_agent\b|\bthomas(\.exe)?\s+serve\b)') {
      $hits += [pscustomobject]@{
        Pid = $owningPid
        CommandLine = $cmd
      }
    }
  }
  return $hits
}

Ensure-Installed

function Invoke-FirstRunQuickSetup {
  if ($NoInstall) { return }

  $statusPath = Join-Path $Root "runtime\\setup\\last_setup.txt"
  if (Test-Path $statusPath) { return }

  $setupScript = Join-Path $Root "scripts\\setup.ps1"
  if (-not (Test-Path $setupScript)) { return }

  Write-Host "[thomas] First launch detected. Running quick setup..."
  $code = 0
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript -Easy -AutoInstallTools -NoPrompt -SkipInstall -SkipDoctor
    $code = $LASTEXITCODE
  } catch {
    $code = 1
  }

  if ($code -ne 0) {
    Write-Host "[thomas] Quick setup did not complete cleanly. You can continue and run setup.cmd later."
  }
}

Invoke-FirstRunQuickSetup

function Stop-ThomasServerOnPort([int]$P) {
  $stoppedAny = $false

  # Stop tray agents bound to this port first; otherwise they immediately
  # respawn the server we are trying to reclaim.
  try {
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $pyProcs) {
      $procId = [int]$proc.ProcessId
      if ($procId -le 0) { continue }
      $procCmd = [string]$proc.CommandLine
      if (-not $procCmd) { continue }
      if ($procCmd -match '(?i)-m\\s+thomas\\.tray_agent\\b' -and $procCmd -match ("(?i)(--port\\s+{0}\\b|--port={0}\\b)" -f $P)) {
        Write-Host ("[thomas] Found Thomas tray agent on port {0} (pid {1}); stopping it..." -f $P, $procId)
        try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch { }
        $stoppedAny = $true
      }
    }
  } catch { }

  $listeners = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
  if (-not $listeners) {
    if ($stoppedAny) { Start-Sleep -Milliseconds 500 }
    return $stoppedAny
  }

  foreach ($l in $listeners) {
    # Avoid PowerShell's built-in $PID (read-only) which is case-insensitive.
    $owningPid = [int]$l.OwningProcess
    if ($owningPid -le 0) { continue }

    $cmd = $null
    try {
      $cmd = (Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $owningPid) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)
    } catch { }

    if ($cmd -and $cmd -match '(?i)(-m\\s+thomas(\\.server)?(\\s+serve)?\\b|\\bthomas(\\.exe)?\\s+serve\\b)') {
      Write-Host ("[thomas] Port {0} is in use by an existing Thomas server (pid {1}); stopping it..." -f $P, $owningPid)
      try { Stop-Process -Id $owningPid -Force -ErrorAction SilentlyContinue } catch { }
      $stoppedAny = $true
    }
  }

  if ($stoppedAny) { Start-Sleep -Milliseconds 500 }
  return $stoppedAny
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

function Get-CloudEnvVarName {
  param([string]$Profile)
  return "THOMAS_MODELS_" + $Profile.ToUpperInvariant() + "_API_KEY"
}

function Show-DefaultModelWarning {
  $defaultModel = Get-DefaultModelName
  if (-not $defaultModel) { return }

  if ($defaultModel -eq "local") {
    return
  }

  if ($defaultModel -eq "codex") {
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $codex) { $codex = Get-Command codex.cmd -ErrorAction SilentlyContinue }
    if (-not $codex) { $codex = Get-Command codex.exe -ErrorAction SilentlyContinue }
    if (-not $codex) {
      Write-Host "[thomas] WARNING: default_model is 'codex' but Codex CLI is not installed."
      Write-Host "[thomas] Install with: npm i -g @openai/codex"
    }
    return
  }

  $envName = Get-CloudEnvVarName $defaultModel
  $envValue = [Environment]::GetEnvironmentVariable($envName, "Process")
  if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "User") }
  if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "Machine") }
  $cfgKey = Get-ProfileApiKeyFromToml -Profile $defaultModel
  if (-not $envValue -and -not $cfgKey) {
    Write-Host ("[thomas] WARNING: default_model '{0}' has no API key configured." -f $defaultModel)
    Write-Host ("[thomas] Run setup.cmd or set {0} before sending chat requests." -f $envName)
  }
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
Show-DefaultModelWarning

# Fast-path: if a healthy Thomas instance is already bound to the target port, reuse it.
$existingThomas = Get-ThomasListenersOnPort $Port
if ($existingThomas.Count -gt 0 -and (Test-ThomasHttpOnPort $Port)) {
  $existingUrl = "http://$BindHost`:$Port/"
  $pidText = ($existingThomas | ForEach-Object { $_.Pid } | Select-Object -Unique) -join ","
  Write-Host ("[thomas] Thomas is already healthy on port {0} (pid {1}); reusing existing instance." -f $Port, $pidText)
  if (-not $NoBrowser) {
    try { Start-Process $existingUrl | Out-Null } catch { }
  }
  exit 0
}

# Prefer a stable URL. If the chosen port is already taken by another Thomas server/tray, stop it.
Stop-ThomasServerOnPort $Port | Out-Null

$FreePort = Find-FreePort $Port
if ($FreePort -eq 0) {
  Write-Host "[thomas] ERROR: No free port found in range $Port..$($Port + 25)."
  Invoke-BootDoctor -Reason ("No free port found in range {0}..{1}" -f $Port, ($Port + 25)) -DiagPort $Port
  exit 2
}

if ($FreePort -ne $Port) {
  if ($StrictPort) {
    Write-Host "[thomas] ERROR: Port $Port is busy and -StrictPort was requested."
    Write-Host "[thomas] Re-run without -StrictPort to auto-select a free port."
    Invoke-BootDoctor -Reason ("Requested strict port {0} is busy." -f $Port) -DiagPort $Port
    exit 2
  }
  if ($AutoPort) {
    Write-Host "[thomas] Port $Port is busy; using $FreePort because -AutoPort is enabled."
  } else {
    Write-Host "[thomas] Port $Port is busy; auto-selecting $FreePort."
  }
  $Port = $FreePort
}

$Url = "http://$BindHost`:$Port/"
Write-Host ""
Write-Host "[thomas] UI: $Url"
Write-Host "[thomas] If this stays on \"ready\" but won't answer, check thomas.toml model endpoints."
Write-Host ""

# ---------------------------------------------------------------------------
# Mode selection: Tray Agent (default) or direct server
# ---------------------------------------------------------------------------

if (-not $NoTray) {
  # Default: Start with tray agent (includes server + tray icon + auto-restart)
  Write-Host "[thomas] Starting Thomas Suite (Tray Agent + Server)..."
  Write-Host "[thomas] Tray icon will appear in system tray. Right-click for options."
  Write-Host ""

  # Ensure pystray is installed for tray icon
  $pystrayCheck = Invoke-NativeQuiet $VenvPy @("-c", "import pystray")
  if ($pystrayCheck -ne 0) {
    Write-Host "[thomas] Installing tray icon dependencies..."
    Invoke-Native $VenvPy @("-m", "pip", "install", "pystray", "pillow", "win10toast", "--quiet") | Out-Null
  }

  if (-not $NoBrowser) {
    # Open browser after a short delay (tray agent starts server in background)
    Start-Sleep -Milliseconds 1500
    try { Start-Process $Url | Out-Null } catch { }
  }

  # Run tray agent (which starts and manages the server)
  & $VenvPy -m thomas.tray_agent --port $Port 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    Invoke-BootDoctor -Reason ("Tray agent exited with code {0}" -f $exitCode) -DiagPort $Port
    exit $exitCode
  }
} else {
  # -NoTray: Run server directly (original behavior)
  Write-Host "[thomas] Starting server directly (no tray icon)..."
  Write-Host ""

  if (-not $NoBrowser) {
    try { Start-Process $Url | Out-Null } catch { }
  }

  & $VenvPy -m thomas.server --host $BindHost --port $Port 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    Invoke-BootDoctor -Reason ("Server exited with code {0}" -f $exitCode) -DiagPort $Port
    exit $exitCode
  }
}
