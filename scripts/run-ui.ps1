param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8899,
  [switch]$AutoPort,
  [switch]$StrictPort,
  [switch]$Restart,
  [switch]$NoBrowser,
  [switch]$NoInstall,
  [switch]$ConfirmedInstallChanges,
  [switch]$NoTray,
  [switch]$Tray,
  [switch]$Headless,
  [switch]$NoMonolithWatch,
  [string]$DeepLink = "",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONDONTWRITEBYTECODE = "1"

if ($Tray) {
  $NoTray = $false
} elseif (-not $PSBoundParameters.ContainsKey('NoTray')) {
  $NoTray = $true
}

if ([string]::IsNullOrWhiteSpace($DeepLink) -and $RemainingArgs) {
  foreach ($candidate in $RemainingArgs) {
    $text = [string]$candidate
    if ($text -like 'thomas://*') {
      $DeepLink = $text
      break
    }
  }
}

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

$script:SelectedSecurityProfile = "balanced"

function Normalize-SecurityProfileName {
  param(
    [string]$ProfileName,
    [string]$Fallback = "balanced"
  )

  $raw = [string]$ProfileName
  if ([string]::IsNullOrWhiteSpace($raw)) {
    return $Fallback
  }

  $normalized = $raw.Trim().ToLowerInvariant().Replace("-", "_")
  switch ($normalized) {
    "standard" { return "balanced" }
    "default" { return "balanced" }
    "balanced" { return "balanced" }
    "builder" { return "hands_on" }
    "hands_on" { return "hands_on" }
    "locked" { return "review_only" }
    "review_only" { return "review_only" }
    "check_only" { return "review_only" }
    default { return $Fallback }
  }
}

function Get-ConfiguredSecurityProfileName {
  $cfgPath = Join-Path $Root "thomas.toml"
  if (-not (Test-Path $cfgPath)) { return "balanced" }

  try {
    $tomlText = Get-Content $cfgPath -Raw -ErrorAction Stop
  } catch {
    return "balanced"
  }

  $section = [regex]::Match($tomlText, '(?ms)^\[security\]\s*(?<body>.*?)(?=^\[|\z)')
  if (-not $section.Success) { return "balanced" }

  $match = [regex]::Match($section.Groups["body"].Value, '(?m)^\s*profile\s*=\s*"(?<value>[^"]+)"')
  if (-not $match.Success) { return "balanced" }

  return (Normalize-SecurityProfileName -ProfileName $match.Groups["value"].Value -Fallback "balanced")
}

function Get-EffectiveSecurityProfile {
  $candidate = [string]$script:SelectedSecurityProfile
  if ([string]::IsNullOrWhiteSpace($candidate)) {
    return "balanced"
  }
  return (Normalize-SecurityProfileName -ProfileName $candidate -Fallback "balanced")
}

function Test-InstallChangesAllowed {
  return ((Get-EffectiveSecurityProfile) -ne "review_only")
}

function Confirm-LauncherMutation {
  param(
    [Parameter(Mandatory = $true)][string]$DisplayName,
    [Parameter(Mandatory = $true)][string]$Reason,
    [string]$Tradeoff = "Installing tools or runtime dependencies mutates this machine outside the committed repo state."
  )

  if ($NoInstall) {
    Write-Host ("[thomas] {0} is required, but -NoInstall blocks launcher-managed changes." -f $DisplayName)
    return $false
  }
  if (-not (Test-InstallChangesAllowed)) {
    Write-Host ("[thomas] Install Guard mode '{0}' blocks launcher-managed changes for {1}." -f (Get-EffectiveSecurityProfile), $DisplayName)
    return $false
  }
  if ($ConfirmedInstallChanges) {
    return $true
  }

  Write-Host ("[thomas] {0} is required." -f $DisplayName)
  Write-Host ("[thomas] Why Thomas wants it: {0}" -f $Reason)
  Write-Host ("[thomas] Security tradeoff: {0}" -f $Tradeoff)
  Write-Host "[thomas] Re-run with -ConfirmedInstallChanges or run scripts\\setup.ps1 to approve the change."
  return $false
}

function Test-WingetAvailable {
  $winget = Get-CommandPathAny @("winget", "winget.exe")
  return -not [string]::IsNullOrWhiteSpace($winget)
}

function Ensure-ThomasProtocolRegistration {
  try {
    $scriptPath = (Resolve-Path (Join-Path $Root "scripts\run-ui.ps1")).Path
    $powershellExe = Get-CommandPathAny @("powershell.exe", "powershell")
    if ([string]::IsNullOrWhiteSpace($scriptPath) -or [string]::IsNullOrWhiteSpace($powershellExe)) {
      return
    }

    $protocolKey = 'HKCU:\Software\Classes\thomas'
    $defaultIconKey = Join-Path $protocolKey 'DefaultIcon'
    $commandKey = Join-Path $protocolKey 'shell\open\command'
    $commandValue = ('"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -DeepLink "%1"' -f $powershellExe, $scriptPath)

    New-Item -Path $protocolKey -Force | Out-Null
    New-Item -Path $defaultIconKey -Force | Out-Null
    New-Item -Path $commandKey -Force | Out-Null
    Set-Item -Path $protocolKey -Value 'URL:Thomas Protocol'
    Set-ItemProperty -Path $protocolKey -Name 'URL Protocol' -Value ''
    Set-Item -Path $defaultIconKey -Value ('"{0}",0' -f $powershellExe)
    Set-Item -Path $commandKey -Value $commandValue
  } catch {
    Write-Host ('[thomas] WARNING: could not register thomas:// protocol handler ({0})' -f $_.Exception.Message)
  }
}

function Get-ThomasLaunchUrl {
  param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [string]$RequestedDeepLink
  )

  $base = [string]$BaseUrl
  $deepLink = [string]$RequestedDeepLink
  if ([string]::IsNullOrWhiteSpace($deepLink)) {
    return $base
  }

  $separator = '?'
  if ($base.Contains('?')) {
    $separator = '&'
  }
  $encodedDeepLink = [System.Uri]::EscapeDataString($deepLink)
  return ("{0}{1}nav=marketplace&thomas_deep_link={2}" -f $base, $separator, $encodedDeepLink)
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

  if (-not (Confirm-LauncherMutation -DisplayName "Python 3.11+" -Reason "Thomas needs Python to run the local server and CLI helpers." -Tradeoff "Installing Python adds a system runtime managed outside the repo lockfiles.")) {
    Write-Host "[thomas] Python is missing. Launcher-managed installation is disabled until you explicitly approve it."
    return $null
  }

  Write-Host "[thomas] Python not found. Installing after explicit approval..."
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

function Test-VenvValid {
  param([string]$VenvRoot)

  $cfg = Join-Path $VenvRoot "pyvenv.cfg"
  $py = Join-Path $VenvRoot "Scripts\\python.exe"
  return ((Test-Path $cfg) -and (Test-Path $py))
}

$script:SelectedSecurityProfile = Get-ConfiguredSecurityProfileName
Write-Host ("[thomas] Install Guard mode: {0}" -f $script:SelectedSecurityProfile)

Ensure-ThomasProtocolRegistration

$SysPy = Ensure-SystemPython
if (-not $SysPy) {
  Write-Host "[thomas] ERROR: Python not found in PATH."
  Write-Host "[thomas] Install Python 3.10+ and try again."
  exit 2
}

$VenvRoot = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvRoot "Scripts\\python.exe"
if (-not (Test-VenvValid $VenvRoot)) {
  if (-not (Confirm-LauncherMutation -DisplayName "Thomas virtual environment" -Reason "Thomas needs a local Python virtual environment in .venv to isolate runtime packages." -Tradeoff "Recreating .venv can add or replace installed Python packages on this machine.")) {
    Write-Host "[thomas] .venv is missing or incomplete. Launcher-managed repair is disabled until you explicitly approve it."
    exit 2
  }

  if (Test-Path $VenvRoot) {
    Write-Host "[thomas] Existing .venv is incomplete. Recreating it..."
    Remove-Item -Recurse -Force $VenvRoot -ErrorAction Stop
  }

  Write-Host "[thomas] Creating venv in .venv..."
  if ($SysPy.Kind -eq "py") {
    & $SysPy.Path -3 -m venv .venv
  } else {
    & $SysPy.Path -m venv .venv
  }

  if (-not (Test-VenvValid $VenvRoot)) {
    Write-Host "[thomas] ERROR: venv creation failed."
    exit 2
  }
}

function Ensure-Installed {
  if ($NoInstall) { return }

  # Install only if missing deps (keeps repeat runs fast).
  $probe = Invoke-NativeQuiet $VenvPy @("-c", "import aiohttp, cryptography, httpx, prompt_toolkit; from PIL import Image")
  if ($probe -ne 0) {
    if (-not (Confirm-LauncherMutation -DisplayName "Thomas runtime dependencies" -Reason "Thomas needs the checked-in Python server dependencies installed into .venv." -Tradeoff "pip install will resolve and add Python packages into the local runtime environment.")) {
      throw "[thomas] Runtime dependencies are missing and launcher-managed installation was not approved."
    }
    Write-Host "[thomas] Installing runtime dependencies (editable) ..."
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server,repl]", "--disable-pip-version-check")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
    return
  }

  # Ensure the editable package is present.
  $show = Invoke-NativeQuiet $VenvPy @("-m", "pip", "show", "thomas-ai")
  if ($show -ne 0) {
    if (-not (Confirm-LauncherMutation -DisplayName "Thomas editable package" -Reason "The Thomas package must be installed into .venv before the launcher can start the server." -Tradeoff "pip install will register the local repo as an editable package in the virtual environment.")) {
      throw "[thomas] Thomas is not installed in .venv and launcher-managed installation was not approved."
    }
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server,repl]", "--disable-pip-version-check")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
  }
}

function Ensure-DiscordBridgeDeps {
  if ($NoInstall) { return }

  $bridgeDepsScript = Join-Path $Root "scripts\ensure_discord_bridge_deps.ps1"
  if (-not (Test-Path $bridgeDepsScript)) { return }

  $powershellExe = Get-CommandPathAny @("powershell.exe", "powershell")
  if ([string]::IsNullOrWhiteSpace($powershellExe)) { return }

  $code = Invoke-NativeQuiet $powershellExe @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $bridgeDepsScript,
    "-Root", $Root
  )
  if ($code -ne 0) {
    throw "[thomas] Embedded Discord bridge dependency sync failed (exit $code)"
  }
}

function Find-FreePort([int]$Preferred) {
  for ($p = $Preferred; $p -le ($Preferred + 25); $p++) {
    $inUse = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not $inUse) { return $p }
  }
  return 0
}

function Invoke-ThomasProbeRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [int]$TimeoutSec = 2
  )

  try {
    $resp = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec -Method Get -ErrorAction Stop
    return [pscustomobject]@{ Ok = ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400); StatusCode = [int]$resp.StatusCode; Detail = ("HTTP {0}" -f [int]$resp.StatusCode) }
  } catch {
    $statusCode = 0
    try { $statusCode = [int]$_.Exception.Response.StatusCode.value__ } catch { }
    $ok = ($statusCode -gt 0 -and $statusCode -lt 500 -and $statusCode -notin @(500, 502, 503, 504))
    $detail = if ($statusCode -gt 0) { "HTTP {0}" -f $statusCode } else { $_.Exception.Message }
    return [pscustomobject]@{ Ok = $ok; StatusCode = [int]$statusCode; Detail = $detail }
  }
}

function Get-ThomasBootHealth {
  param([Parameter(Mandatory = $true)][int]$P)

  $listening = $false
  try {
    $listening = [bool](Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue)
  } catch { }

  $probeSpecs = @(
    @{ Id = 'root'; Path = '/'; Class = 'core' },
    @{ Id = 'health'; Path = '/api/health'; Class = 'core' },
    @{ Id = 'models'; Path = '/api/models'; Class = 'important' },
    @{ Id = 'recovery_notice'; Path = '/api/bootdoctor/recovery_notice'; Class = 'important' }
  )

  $probeResults = @()
  foreach ($spec in $probeSpecs) {
    if ($listening) {
      $probe = Invoke-ThomasProbeRequest -Uri ("http://127.0.0.1:{0}{1}" -f $P, $spec.Path)
      $probeResults += [pscustomobject]@{ id = $spec.Id; class = $spec.Class; path = $spec.Path; ok = [bool]$probe.Ok; status = [int]$probe.StatusCode; detail = [string]$probe.Detail }
    } else {
      $probeResults += [pscustomobject]@{ id = $spec.Id; class = $spec.Class; path = $spec.Path; ok = $false; status = 0; detail = 'port not listening' }
    }
  }

  $coreFailed = ($probeResults | Where-Object { $_.class -eq 'core' -and -not $_.ok }).Count -gt 0
  $importantFailed = ($probeResults | Where-Object { $_.class -ne 'core' -and -not $_.ok }).Count -gt 0
  $severity = if (-not $listening -or $coreFailed) { 'fatal' } elseif ($importantFailed) { 'degraded' } else { 'healthy' }
  return [pscustomobject]@{ Ready = ($severity -ne 'fatal'); Severity = $severity; Listening = $listening; ProbeResults = @($probeResults) }
}

function Wait-ThomasBootHealth {
  param(
    [Parameter(Mandatory = $true)][int]$P,
    [int]$Attempts = 12,
    [int]$DelayMs = 300
  )

  $attemptCount = [Math]::Max(1, $Attempts)
  $last = $null
  for ($i = 0; $i -lt $attemptCount; $i++) {
    $last = Get-ThomasBootHealth -P $P
    if ($last.Ready) { return $last }
    if ($i -lt ($attemptCount - 1)) {
      Start-Sleep -Milliseconds ([Math]::Max(50, $DelayMs))
    }
  }
  if ($null -eq $last) {
    $last = Get-ThomasBootHealth -P $P
  }
  return $last
}

function Test-ThomasHttpOnPort([int]$P) {
  $state = Get-ThomasBootHealth -P $P
  return [bool]$state.Ready
}

function Wait-ThomasHttpOnPort {
  param(
    [Parameter(Mandatory = $true)][int]$P,
    [int]$Attempts = 12,
    [int]$DelayMs = 300
  )

  $state = Wait-ThomasBootHealth -P $P -Attempts $Attempts -DelayMs $DelayMs
  return [bool]$state.Ready
}

function Get-FileTailText {
  param(
    [string]$Path,
    [int]$MaxLines = 200,
    [int]$MaxChars = 16000
  )

  if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
  if (-not (Test-Path $Path)) { return "" }

  try {
    $text = ((Get-Content -Path $Path -Tail ([Math]::Max(10, $MaxLines)) -ErrorAction Stop) -join "`n").Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return "" }
    if ($text.Length -gt $MaxChars) {
      return $text.Substring($text.Length - $MaxChars)
    }
    return $text
  } catch {
    return ""
  }
}

function Get-StartupFailureContext {
  param([string[]]$LogPaths)

  $existing = @($LogPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path $_) } | Select-Object -Unique)
  $tail = ""
  foreach ($logPath in $existing) {
    $tail = Get-FileTailText -Path $logPath
    if (-not [string]::IsNullOrWhiteSpace($tail)) {
      break
    }
  }

  return [pscustomobject]@{
    LogPaths = $existing
    StdErrTail = $tail
  }
}

function Get-BootDoctorRuntimeDir {
  return (Join-Path $Root "runtime\boot_doctor")
}

function Clear-BootDoctorRecoveryArtifacts {
  $diagDir = Get-BootDoctorRuntimeDir
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  foreach ($name in @('rescue_status.json', 'recovery_notice.json')) {
    $target = Join-Path $diagDir $name
    if (Test-Path $target) {
      Remove-Item -Path $target -Force -ErrorAction SilentlyContinue
    }
  }
}

function Write-BootDoctorDegradedStatus {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][int]$DiagPort,
    [string]$Message = 'Thomas launched in a degraded state while Boot Doctor investigates.'
  )

  $diagDir = Get-BootDoctorRuntimeDir
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  $statusPath = Join-Path $diagDir 'rescue_status.json'
  $payload = [ordered]@{
    status = 'degraded'
    phase = 'repairing'
    message = $Message
    reason = $Reason
    severity = 'degraded'
    recovered = $true
    blocking = $false
    port = [int]$DiagPort
    repairs = @()
    ai_summary = ''
    recommended_actions = @('retry_repair', 'restart', 'open_rescue')
    probe_results = @()
    updated_at_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $statusPath -Encoding UTF8
}

function Start-BootDoctorBackgroundRepair {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][int]$DiagPort
  )

  $bootDoctorScript = Join-Path $Root 'scripts\bootdoctor.ps1'
  if (-not (Test-Path $bootDoctorScript)) {
    return $null
  }

  try {
    return Start-Process -FilePath 'powershell.exe' -ArgumentList @(
      '-NoProfile',
      '-ExecutionPolicy', 'Bypass',
      '-File', $bootDoctorScript,
      'report',
      '--force',
      '--port', "$DiagPort",
      '--reason', $Reason,
      '--relaunch'
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
  } catch {
    Write-Host ("[thomas] WARNING: unable to start Boot Doctor background repair: {0}" -f $_.Exception.Message)
    return $null
  }
}

function Invoke-BootDoctor {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [int]$DiagPort = 8899,
    [switch]$Relaunch
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
    $bootArgs = @("-m", "thomas.bootdoctor", "report", "--force", "--port", "$DiagPort", "--reason", $Reason, "--report", $report)
    if ($Relaunch) {
      $bootArgs += "--relaunch"
    }
    $cliExit = Invoke-Native $VenvPy $bootArgs
    if ($cliExit -eq 0) {
      $succeeded = $true
    } else {
      Write-Host ("[thomas] bootdoctor report runner failed (exit {0}); trying direct core fallback..." -f $cliExit)
      if (Test-Path $runner) {
        $directArgs = @($runner, "--root", $Root, "--port", "$DiagPort", "--reason", $Reason, "--report", $report)
        if ($Relaunch) {
          $directArgs += "--relaunch"
        }
        $directExit = Invoke-Native $VenvPy $directArgs
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

  if ($Relaunch -and $succeeded) {
    $healthState = Wait-ThomasBootHealth -P $DiagPort -Attempts 34 -DelayMs 300
    $recovered = [bool]$healthState.Ready
    if ($recovered -and $healthState.Severity -eq 'degraded') {
      Write-Host ("[thomas] Boot Doctor kept Thomas available in a degraded state on port {0}." -f $DiagPort)
    } elseif ($recovered) {
      Write-Host ("[thomas] Boot Doctor recovered Thomas on port {0}." -f $DiagPort)
    } else {
      Write-Host ("[thomas] Boot Doctor finished but Thomas is still not ready on port {0}." -f $DiagPort)
    }
  }

  Write-Host ("[thomas] Boot Doctor report: {0}" -f $report)
  if (-not $recovered) {
    try { Start-Process notepad.exe $report | Out-Null } catch { }
  }

  return [pscustomobject]@{
    ReportPath = $report
    Succeeded = $succeeded
    Recovered = $recovered
  }
}

function Open-BootDoctorRescue {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [int]$DiagPort = 8899,
    [string]$LaunchMode = "direct",
    [string]$StdErrTail = "",
    [string[]]$StartupLogPaths = @(),
    [int]$WaitSec = 90
  )

  Write-Host ""
  Write-Host ("[thomas] Boot Doctor rescue: {0}" -f $Reason)

  $diagDir = Join-Path $Root "runtime\boot_doctor"
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $contextPath = Join-Path $diagDir ("startup_context_{0}.json" -f $stamp)
  $payload = [ordered]@{
    created_at_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    reason = $Reason
    attempted_launch_mode = $LaunchMode
    target_port = [int]$DiagPort
    current_health_status = (Get-ThomasBootHealth -P $DiagPort).Severity
    ever_healthy_during_boot = $false
    stderr_tail = [string]$StdErrTail
    startup_log_paths = @($StartupLogPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $contextPath -Encoding UTF8

  $bootDoctorScript = Join-Path $Root "scripts\bootdoctor.ps1"
  if (-not (Test-Path $bootDoctorScript)) {
    Write-Host ("[thomas] WARNING: Boot Doctor launcher missing: {0}" -f $bootDoctorScript)
    return [pscustomobject]@{ Recovered = $false; ContextPath = $contextPath; Process = $null }
  }

  $proc = $null
  try {
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $bootDoctorScript,
      "rescue",
      "--force",
      "--port", "$DiagPort",
      "--reason", $Reason,
      "--startup-context", $contextPath,
      "--relaunch"
    ) -WorkingDirectory $Root -PassThru
  } catch {
    Write-Host ("[thomas] WARNING: unable to launch Boot Doctor rescue window: {0}" -f $_.Exception.Message)
  }

  $healthState = Wait-ThomasBootHealth -P $DiagPort -Attempts ([Math]::Max(20, $WaitSec * 2)) -DelayMs 500
  $recovered = [bool]$healthState.Ready
  if ($recovered -and $healthState.Severity -eq 'degraded') {
    Write-Host ("[thomas] Boot Doctor rescue restored Thomas in a degraded state on port {0}." -f $DiagPort)
  } elseif ($recovered) {
    Write-Host ("[thomas] Boot Doctor rescue recovered Thomas on port {0}." -f $DiagPort)
  }

  return [pscustomobject]@{
    Recovered = $recovered
    ContextPath = $contextPath
    Process = $proc
  }
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
Ensure-DiscordBridgeDeps

function Invoke-FirstRunQuickSetup {
  if ($NoInstall) { return }

  $statusPath = Join-Path $Root "runtime\\setup\\last_setup.txt"
  if (Test-Path $statusPath) { return }

  $setupScript = Join-Path $Root "scripts\\setup.ps1"
  if (-not (Test-Path $setupScript)) { return }

  Write-Host "[thomas] First launch detected. Running quick setup..."
  $code = 0
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript -Easy -NoPrompt -SkipInstall -SkipDoctor
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
      Write-Host "[thomas] Install Node.js and @openai/codex only after explicit approval."
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

function Test-OllamaAutoStartEnabled {
  $raw = [string]$env:THOMAS_AUTO_START_OLLAMA
  if ([string]::IsNullOrWhiteSpace($raw)) {
    return $false
  }

  return $raw.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

$ReuseHealthyInstance = $false
if (-not $Restart) {
  $healthyCandidate = Get-ThomasHealthyCandidate -PreferredPort $Port
  if ($healthyCandidate -and $healthyCandidate.Port) {
    $candidateHealth = Get-ThomasBootHealth -P ([int]$healthyCandidate.Port)
    if ([string]$candidateHealth.Severity -eq "healthy") {
      $Port = [int]$healthyCandidate.Port
      $ReuseHealthyInstance = $true
    }
  }
}

if (Uses-OllamaLocal) {
  if (Test-OllamaAutoStartEnabled) {
    Ensure-OllamaRunning
  } else {
    Write-Host "[thomas] Local Ollama auto-start is disabled. Set THOMAS_AUTO_START_OLLAMA=1 to let the launcher start Ollama."
  }
}
Show-DefaultModelWarning

# Ã¢â€â‚¬Ã¢â€â‚¬ ALWAYS start fresh Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# Kill ALL existing Thomas servers and tray agents so we always run the
# current version from this working tree.  The old "reuse" logic caused
# stale servers to persist after code updates.
if (-not $ReuseHealthyInstance) {
  if ($Restart) {
    Write-Host "[thomas] -Restart requested. Stopping any running Thomas instances first."
  }

  $allListeners = @(Get-ThomasListeners)
  if ($allListeners.Count -gt 0) {
    $allPorts = @($allListeners | Select-Object -ExpandProperty Port -Unique)
    Write-Host ("[thomas] Stopping {0} existing Thomas instance(s) on port(s): {1}" -f $allListeners.Count, ($allPorts -join ", "))
    foreach ($existingPort in $allPorts) {
      Stop-ThomasServerOnPort ([int]$existingPort) | Out-Null
    }
    # Also kill any orphaned tray agents that aren't listening on a port.
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

  # Ensure the target port is clear even if a non-Thomas process holds it.
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
}

# Show what version we're about to start so the user can confirm it's current.
$startingVersion = ""
try {
  $vOut = & $VenvPy -c "from thomas import __version__; print(__version__)" 2>$null
  if ($vOut) { $startingVersion = $vOut.Trim() }
} catch { }
if (-not $startingVersion) { $startingVersion = "unknown" }

$Url = "http://$BindHost`:$Port/"
$LaunchUrl = Get-ThomasLaunchUrl -BaseUrl $Url -RequestedDeepLink $DeepLink
Write-Host ""
Write-Host ("[thomas] Starting Thomas v{0}" -f $startingVersion)
Write-Host "[thomas] UI: $Url"
if (-not [string]::IsNullOrWhiteSpace($DeepLink)) {
  Write-Host "[thomas] Pending install link detected. Thomas will open Marketplace and finish the plugin install."
}
Write-Host "[thomas] If this stays on 'ready' but won't answer, check thomas.toml model endpoints."
Write-Host ""

if ($ReuseHealthyInstance) {
  Write-Host ("[thomas] Reusing healthy Thomas instance on port {0}." -f $Port)
  if (-not $NoBrowser) {
    try { Start-Process $LaunchUrl | Out-Null } catch { }
  }
  exit 0
}

function Start-MonolithWatch {
  if ($NoMonolithWatch) { return $null }

  $raw = [string]$env:THOMAS_MONOLITH_WATCH
  if (-not $raw) {
    return $null
  }
  $flag = $raw.Trim().ToLowerInvariant()
  if ($flag -notin @("1", "true", "yes", "on")) {
    return $null
  }

  Write-Host "[thomas] Live monolith guard watcher: enabled (set THOMAS_MONOLITH_WATCH=0 to disable)."
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

function Start-ThomasStartupRecoveryWatch {
  $watchScript = Join-Path $Root "scripts\startup_recovery_watch.ps1"
  if (-not (Test-Path $watchScript)) {
    Write-Host ("[thomas] WARNING: startup recovery watcher missing: {0}" -f $watchScript)
    return $null
  }

  $watchArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $watchScript,
    "-Root", $Root,
    "-Port", "$Port",
    "-LaunchUrl", $LaunchUrl,
    "-LaunchMode", $(if ($NoTray) { "direct" } else { "tray" })
  )
  if ($NoBrowser) {
    $watchArgs += "-NoBrowser"
  }

  try {
    return Start-Process `
      -FilePath "powershell.exe" `
      -ArgumentList $watchArgs `
      -WorkingDirectory $Root `
      -WindowStyle Hidden `
      -PassThru
  } catch {
    Write-Host ("[thomas] WARNING: unable to start startup recovery watcher: {0}" -f $_.Exception.Message)
    return $null
  }
}

function Stop-ThomasStartupRecoveryWatch {
  param($WatchProc)
  if ($null -eq $WatchProc) { return }
  try {
    if (-not $WatchProc.HasExited) {
      Stop-Process -Id $WatchProc.Id -Force -ErrorAction SilentlyContinue
    }
  } catch { }
}

function Invoke-ThomasRuntime {
  param([Parameter(Mandatory = $true)][string[]]$Args)

  & $VenvPy @Args
  $exitCode = $LASTEXITCODE
  if ($null -eq $exitCode) {
    return 0
  }
  return [int]$exitCode
}

function Start-DetachedThomasServer {
  param(
    [Parameter(Mandatory = $true)][string]$BindAddress,
    [Parameter(Mandatory = $true)][int]$ServerPort
  )

  $logDir = Join-Path $Root 'runtime\logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $stdoutLog = Join-Path $logDir 'server_stdout.log'
  $stderrLog = Join-Path $logDir 'server_stderr.log'

  try {
    $proc = Start-Process `
      -FilePath $VenvPy `
      -ArgumentList @('-m', 'thomas.server', '--host', $BindAddress, '--port', "$ServerPort") `
      -WorkingDirectory $Root `
      -RedirectStandardOutput $stdoutLog `
      -RedirectStandardError $stderrLog `
      -PassThru
  } catch {
    Write-Host ("[thomas] ERROR: failed to launch detached server: {0}" -f $_.Exception.Message)
    return [pscustomobject]@{ Process = $null; StdoutLog = $stdoutLog; StderrLog = $stderrLog; Healthy = $false }
  }

  $healthState = Wait-ThomasBootHealth -P $ServerPort -Attempts 70 -DelayMs 500
  return [pscustomobject]@{
    Process = $proc
    StdoutLog = $stdoutLog
    StderrLog = $stderrLog
    Healthy = [bool]$healthState.Ready
    HealthState = $healthState
    Severity = [string]$healthState.Severity
  }
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
    if (-not (Confirm-LauncherMutation -DisplayName "Tray icon dependencies" -Reason "Tray mode needs pystray, pillow, and win10toast for the Windows tray experience." -Tradeoff "Installing tray dependencies adds extra Python packages to the local runtime.")) {
      Write-Host "[thomas] Tray dependencies are missing. Start with -NoTray or rerun with -ConfirmedInstallChanges."
      exit 2
    }
    Write-Host "[thomas] Installing tray icon dependencies..."
    Invoke-Native $VenvPy @("-m", "pip", "install", "pystray", "pillow", "win10toast", "--quiet") | Out-Null
  }

  $startupWatchProc = Start-ThomasStartupRecoveryWatch
  $watchProc = Start-MonolithWatch
  try {
    # Run tray agent (which starts and manages the server)
    $exitCode = Invoke-ThomasRuntime @("-m", "thomas.tray_agent", "--port", "$Port")
    if ($exitCode -ne 0) {
      Stop-ThomasStartupRecoveryWatch $startupWatchProc
      $bootContext = Get-StartupFailureContext -LogPaths @(
        (Join-Path $Root 'runtime\logs\server_stderr.log'),
        (Join-Path $Root 'runtime\logs\server_stdout.log')
      )
      $doctorResult = Open-BootDoctorRescue -Reason ("Tray agent exited with code {0}" -f $exitCode) -DiagPort $Port -LaunchMode "tray" -StdErrTail $bootContext.StdErrTail -StartupLogPaths $bootContext.LogPaths
      if ($doctorResult -and $doctorResult.Recovered) {
        if (-not $NoBrowser) {
          try { Start-Process $LaunchUrl | Out-Null } catch { }
        }
        exit 0
      }
      exit $exitCode
    }
  } finally {
    Stop-ThomasStartupRecoveryWatch $startupWatchProc
    Stop-MonolithWatch $watchProc
  }
} else {
  # -NoTray: Run server directly as a detached process and gate success on health.
  Write-Host "[thomas] Starting server directly (no tray icon)..."
  Write-Host ""

  $watchProc = Start-MonolithWatch
  try {
    Clear-BootDoctorRecoveryArtifacts
    $launch = Start-DetachedThomasServer -BindAddress $BindHost -ServerPort $Port
    if ($launch -and $launch.Healthy) {
      if ([string]$launch.Severity -eq 'degraded') {
        $reason = "Detached server launched in a degraded state on port {0}." -f $Port
        Write-BootDoctorDegradedStatus -Reason $reason -DiagPort $Port
        Start-BootDoctorBackgroundRepair -Reason $reason -DiagPort $Port | Out-Null
      }
      if (-not $NoBrowser) {
        try { Start-Process $LaunchUrl | Out-Null } catch { }
      }
      exit 0
    }

    $serverPid = $null
    if ($launch -and $launch.Process) {
      $serverPid = $launch.Process.Id
      try { Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue } catch { }
    }

    $reason = if ($serverPid) {
      "Detached server failed to become ready on port {0} (pid {1})." -f $Port, $serverPid
    } else {
      "Detached server failed to launch on port {0}." -f $Port
    }
    $bootContext = Get-StartupFailureContext -LogPaths @($launch.StderrLog, $launch.StdoutLog)
    $doctorResult = Open-BootDoctorRescue -Reason $reason -DiagPort $Port -LaunchMode "direct" -StdErrTail $bootContext.StdErrTail -StartupLogPaths $bootContext.LogPaths
    if ($doctorResult -and $doctorResult.Recovered) {
      if (-not $NoBrowser) {
        try { Start-Process $LaunchUrl | Out-Null } catch { }
      }
      exit 0
    }
    exit 1
  } finally {
    Stop-MonolithWatch $watchProc
  }
}
