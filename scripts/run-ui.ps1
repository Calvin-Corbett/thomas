param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8899,
  [switch]$AutoPort,
  [switch]$StrictPort,
  [switch]$NoBrowser,
  [switch]$NoInstall,
  [switch]$NoTray,
  [switch]$Headless,
  [switch]$NoMonolithWatch
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Invoke-NativeCore {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args,
    [switch]$Quiet
  )

  $quotedArgs = @()
  foreach ($arg in $Args) {
    $text = [string]$arg
    if ($text -match '[\s"]') {
      $text = '"' + ($text -replace '"', '\"') + '"'
    }
    $quotedArgs += $text
  }
  $argLine = ($quotedArgs -join " ")

  $outFile = [System.IO.Path]::GetTempFileName()
  $errFile = [System.IO.Path]::GetTempFileName()
  try {
    $proc = Start-Process `
      -FilePath $Exe `
      -ArgumentList $argLine `
      -NoNewWindow `
      -Wait `
      -PassThru `
      -RedirectStandardOutput $outFile `
      -RedirectStandardError $errFile `
      -ErrorAction Stop

    if (-not $Quiet) {
      if (Test-Path $outFile) {
        $stdout = Get-Content -Path $outFile -ErrorAction SilentlyContinue
        if ($stdout) { $stdout | Out-Host }
      }
      if (Test-Path $errFile) {
        $stderr = Get-Content -Path $errFile -ErrorAction SilentlyContinue
        if ($stderr) { $stderr | Out-Host }
      }
    }

    return [int]$proc.ExitCode
  } catch {
    if (-not $Quiet) {
      Write-Host ("[thomas] ERROR: failed to run native command: {0} ({1})" -f $Exe, $_.Exception.Message)
    }
    return 1
  } finally {
    try { Remove-Item -Path $outFile -Force -ErrorAction SilentlyContinue } catch { }
    try { Remove-Item -Path $errFile -Force -ErrorAction SilentlyContinue } catch { }
  }
}

function Invoke-NativeQuiet {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  return (Invoke-NativeCore -Exe $Exe -Args $Args -Quiet)
}

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  return (Invoke-NativeCore -Exe $Exe -Args $Args)
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

function Wait-ThomasHttpOnPort {
  param(
    [Parameter(Mandatory = $true)][int]$P,
    [int]$Attempts = 12,
    [int]$DelayMs = 300
  )

  $attemptCount = [Math]::Max(1, $Attempts)
  for ($i = 0; $i -lt $attemptCount; $i++) {
    if (Test-ThomasHttpOnPort $P) { return $true }
    if ($i -lt ($attemptCount - 1)) {
      Start-Sleep -Milliseconds ([Math]::Max(50, $DelayMs))
    }
  }
  return $false
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
  $runner = Join-Path $Root "scripts\\run_boot_doctor_direct.py"
  $cliExit = -1
  $directExit = -1
  $succeeded = $false

  try {
    $cliExit = Invoke-Native $VenvPy @("-m", "thomas.bootdoctor", "report", "--force", "--port", "$DiagPort", "--reason", $Reason, "--report", $report)
    if ($cliExit -eq 0) {
      $succeeded = $true
    } else {
      Write-Host ("[thomas] bootdoctor report runner failed (exit {0}); trying direct core fallback..." -f $cliExit)
      if (Test-Path $runner) {
        $directExit = Invoke-Native $VenvPy @($runner, "--root", $Root, "--port", "$DiagPort", "--reason", $Reason, "--report", $report)
        if ($directExit -eq 0) {
          $succeeded = $true
        }
      } else {
        Write-Host ("[thomas] WARNING: direct Boot Doctor runner missing: {0}" -f $runner)
      }
    }
  } catch {
    $detail = $_.Exception.Message
    $failure = @(
      "Thomas Boot Doctor invocation raised an exception."
      ("Reason: {0}" -f $Reason)
      ("Port: {0}" -f $DiagPort)
      ("Error: {0}" -f $detail)
      ("Generated (UTC): {0}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))
    ) -join [Environment]::NewLine
    Set-Content -Path $report -Value $failure -Encoding UTF8
  }

  if (-not $succeeded) {
    $failure = @(
      "Thomas Boot Doctor execution failed."
      ("Reason: {0}" -f $Reason)
      ("Port: {0}" -f $DiagPort)
      ("CLI exit code: {0}" -f $cliExit)
      ("Direct fallback exit code: {0}" -f $directExit)
      ("Generated (UTC): {0}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))
      ""
      "Review console output above for traceback details."
    ) -join [Environment]::NewLine
    Set-Content -Path $report -Value $failure -Encoding UTF8
  }

  Write-Host ("[thomas] Boot Doctor report: {0}" -f $report)
  try { Start-Process notepad.exe $report | Out-Null } catch { }
}

function Get-ThomasListenersOnPort([int]$P) {
  $hits = Get-ThomasListeners
  if (-not $hits) { return @() }
  return @($hits | Where-Object { [int]$_.Port -eq $P })
}

function Test-ThomasProcessCommand([string]$CommandLine) {
  $cmd = [string]$CommandLine
  if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
  return $cmd -match '(?i)(-m\s+thomas(\.server)?(\s+serve)?\b|-m\s+thomas\.tray_agent\b|\bthomas(\.exe)?\s+serve\b)'
}

function Get-ThomasListeners {
  $hits = @()
  $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
  if (-not $listeners) { return $hits }
  foreach ($l in $listeners) {
    $owningPid = [int]$l.OwningProcess
    if ($owningPid -le 0) { continue }
    $cmd = $null
    try {
      $cmd = (Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $owningPid) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)
    } catch { }
    if (Test-ThomasProcessCommand $cmd) {
      $hits += [pscustomobject]@{
        Port = [int]$l.LocalPort
        Pid = $owningPid
        CommandLine = $cmd
      }
    }
  }
  return $hits
}

function Get-ThomasHealthyCandidate {
  param([int]$PreferredPort)

  $listeners = @(Get-ThomasListeners)
  if (-not $listeners.Count) { return $null }

  $ports = @($listeners | Select-Object -ExpandProperty Port -Unique | Sort-Object)
  $orderedPorts = @()
  if ($ports -contains $PreferredPort) { $orderedPorts += $PreferredPort }
  $orderedPorts += @($ports | Where-Object { [int]$_ -ne $PreferredPort })

  foreach ($candidatePort in $orderedPorts) {
    if (Wait-ThomasHttpOnPort -P ([int]$candidatePort)) {
      return [pscustomobject]@{
        Port = [int]$candidatePort
        Listeners = @($listeners | Where-Object { [int]$_.Port -eq [int]$candidatePort })
        AllListeners = $listeners
      }
    }
  }

  return [pscustomobject]@{
    Port = $null
    Listeners = @()
    AllListeners = $listeners
  }
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
      if ($procCmd -match '(?i)-m\s+thomas\.tray_agent\b' -and $procCmd -match ("(?i)(--port\s+{0}\b|--port={0}\b)" -f $P)) {
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

    if ($cmd -and $cmd -match '(?i)(-m\s+thomas(\.server)?(\s+serve)?\b|\bthomas(\.exe)?\s+serve\b)') {
      # If this server is managed by a tray agent, stop the parent tray first
      # so it does not immediately respawn the duplicate server.
      try {
        $procObj = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $owningPid) -ErrorAction SilentlyContinue
        $parentPid = [int]$procObj.ParentProcessId
        if ($parentPid -gt 0) {
          $parentCmd = [string](Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $parentPid) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)
          if ($parentCmd -and $parentCmd -match '(?i)-m\s+thomas\.tray_agent\b') {
            Write-Host ("[thomas] Found tray parent for duplicate server on port {0} (pid {1}); stopping tray parent..." -f $P, $parentPid)
            try { Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue } catch { }
            $stoppedAny = $true
          }
        }
      } catch { }

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
  if ($t -match 'default_model\s*=\s*\"local\"' -and $t -match 'base_url\s*=\s*\"http://(localhost|127\.0\.0\.1):11434') {
    return $true
  }
  return $false
}

function Get-DefaultModelName {
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return "" }
  $t = Get-Content $cfgPath -Raw
  $m = [regex]::Match($t, '(?m)^\s*default_model\s*=\s*\"(?<value>[^\"]+)\"')
  if (-not $m.Success) { return "" }
  return $m.Groups["value"].Value.Trim().ToLowerInvariant()
}

function Get-ProfileApiKeyFromToml {
  param([string]$Profile)
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return "" }
  $t = Get-Content $cfgPath -Raw
  $escaped = [regex]::Escape($Profile)
  $section = [regex]::Match($t, "(?ms)^\[models\.$escaped\]\s*(?<body>.*?)(?=^\[|\z)")
  if (-not $section.Success) { return "" }
  $api = [regex]::Match($section.Groups["body"].Value, '(?m)^\s*api_key\s*=\s*\"(?<key>[^\"]*)\"')
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

# ── ALWAYS start fresh ──────────────────────────────────────────────
# Kill ALL existing Thomas servers and tray agents so we always run the
# current version from this working tree.  The old "reuse" logic caused
# stale servers to persist after code updates.
$allListeners = @(Get-ThomasListeners)
if ($allListeners.Count -gt 0) {
  $allPorts = @($allListeners | Select-Object -ExpandProperty Port -Unique)
  Write-Host ("[thomas] Stopping {0} existing Thomas instance(s) on port(s): {1}" -f $allListeners.Count, ($allPorts -join ", "))
  foreach ($existingPort in $allPorts) {
    Stop-ThomasServerOnPort ([int]$existingPort) | Out-Null
  }
  # Also kill any orphaned tray agents that aren't listening on a port
  try {
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $pyProcs) {
      $procCmd = [string]$proc.CommandLine
      if ($procCmd -and $procCmd -match '(?i)-m\s+thomas\.tray_agent\b') {
        $procId = [int]$proc.ProcessId
        if ($procId -gt 0) {
          Write-Host ("[thomas] Stopping orphaned tray agent (pid {0})" -f $procId)
          try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch { }
        }
      }
    }
  } catch { }
  Start-Sleep -Milliseconds 800
}

# Also ensure the target port is clear (non-Thomas process might hold it)
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

# Show what version we're about to start so the user can confirm it's current.
$startingVersion = ""
try {
  $vOut = & $VenvPy -c "from thomas import __version__; print(__version__)" 2>$null
  if ($vOut) { $startingVersion = $vOut.Trim() }
} catch { }
if (-not $startingVersion) { $startingVersion = "unknown" }

$Url = "http://$BindHost`:$Port/"
Write-Host ""
Write-Host ("[thomas] Starting Thomas v{0}" -f $startingVersion)
Write-Host "[thomas] UI: $Url"
Write-Host "[thomas] If this stays on \"ready\" but won't answer, check thomas.toml model endpoints."
Write-Host ""

function Start-MonolithWatch {
  if ($NoMonolithWatch) { return $null }

  $raw = [string]$env:THOMAS_MONOLITH_WATCH
  if ($raw) {
    $flag = $raw.Trim().ToLowerInvariant()
    if ($flag -in @("0", "false", "no", "off")) {
      return $null
    }
  }

  Write-Host "[thomas] Live monolith guard watcher: enabled (use -NoMonolithWatch to disable)."
  try {
    $proc = Start-Process `
      -FilePath $VenvPy `
      -ArgumentList @("-u", "scripts/watch_monolith_guard.py", "--repo-root", $Root, "--interval", "2.0") `
      -NoNewWindow `
      -PassThru
    return $proc
  } catch {
    Write-Host ("[thomas] WARNING: unable to start live monolith watcher: {0}" -f $_.Exception.Message)
    return $null
  }
}

function Stop-MonolithWatch {
  param($WatchProc)
  if ($null -eq $WatchProc) { return }
  try {
    if (-not $WatchProc.HasExited) {
      Stop-Process -Id $WatchProc.Id -Force -ErrorAction SilentlyContinue
    }
  } catch { }
}

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

  $watchProc = Start-MonolithWatch
  try {
    # Run tray agent (which starts and manages the server)
    $exitCode = Invoke-Native $VenvPy @("-m", "thomas.tray_agent", "--port", "$Port")
    if ($exitCode -ne 0) {
      Invoke-BootDoctor -Reason ("Tray agent exited with code {0}" -f $exitCode) -DiagPort $Port
      exit $exitCode
    }
  } finally {
    Stop-MonolithWatch $watchProc
  }
} else {
  # -NoTray: Run server directly (original behavior)
  Write-Host "[thomas] Starting server directly (no tray icon)..."
  Write-Host ""

  if (-not $NoBrowser) {
    try { Start-Process $Url | Out-Null } catch { }
  }

  $watchProc = Start-MonolithWatch
  try {
    $exitCode = Invoke-Native $VenvPy @("-m", "thomas.server", "--host", "$BindHost", "--port", "$Port")
    if ($exitCode -ne 0) {
      Invoke-BootDoctor -Reason ("Server exited with code {0}" -f $exitCode) -DiagPort $Port
      exit $exitCode
    }
  } finally {
    Stop-MonolithWatch $watchProc
  }
}
