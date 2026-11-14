param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8899,
  [switch]$AutoPort,
  [switch]$StrictPort,
  [switch]$NoBrowser,
  [switch]$NoInstall,
  [switch]$NoTray,
  [switch]$Tray,
  [switch]$Headless,
  [switch]$NoMonolithWatch,
  # Replace a Thomas server that is already running on the port. Without it one that
  # is this copy is reused, and none is replaced while a Build run is in flight.
  [switch]$Restart,
  # Stop the Thomas server on the port and exit. Refused while a Build run is in flight.
  [switch]$Stop,
  # First-run setup may install Node.js, the Codex CLI and Ollama (winget / npm), as
  # THOMAS_AUTO_INSTALL_TOOLS=1 does. Off by default; first launch only, then setup.cmd.
  [switch]$InstallTools,
  # Point the thomas:// handler at this copy even if one is already registered.
  [switch]$RegisterProtocol,
  # Never write the thomas:// handler to the registry.
  [switch]$NoProtocolHandler,
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
$PortNamed = $PSBoundParameters.ContainsKey('Port')  # a -Port you name is the port: the recorded one is never looked at

if ([string]::IsNullOrWhiteSpace($DeepLink) -and $RemainingArgs) {
  foreach ($candidate in $RemainingArgs) {
    $text = [string]$candidate
    if ($text -like 'thomas://*') {
      $DeepLink = $text
      break
    }
  }
}

function Test-PortListening([int]$P) {
  # Get-NetTCPConnection costs ~1s per call on Windows 11 and this runs once per
  # readiness poll. The .NET listener table answers the same question in ~3ms.
  # A failure falls through to $false, matching the -ErrorAction SilentlyContinue
  # the cmdlet calls this replaced used to carry.
  try {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
  } catch {
    return $false
  }
  foreach ($l in $listeners) { if ($l.Port -eq $P) { return $true } }
  return $false
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

function Test-PythonRuns {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string[]]$LauncherArgs = @()
  )
  # Without Python, "python.exe" still resolves: the Store alias, a stub that exits 9009. Trust an
  # interpreter only after it has run and reported a version Thomas supports (pyproject.toml: requires-python >= 3.10).
  $probe = 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)'
  # The Python install manager's py.exe installs a runtime it lacks; a probe must not. Only
  # AUTOMATIC_INSTALL is its off switch (CONFIRM=0 skips the prompt, so it would install).
  $saved = $env:PYTHON_MANAGER_AUTOMATIC_INSTALL
  $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = '0'
  try { $code = Invoke-NativeQuiet $Path @($LauncherArgs + @('-c', $probe)) }
  finally { $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = $saved }
  return ($code -eq 0)
}

function Find-SystemPython {
  foreach ($cmd in @(Get-Command python -All -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' })) {
    if ($cmd.Source -and (Test-PythonRuns -Path $cmd.Source)) { return @{ Kind = "python"; Path = $cmd.Source } }
  }
  # "py -3" is the newest Python installed, so the versions Thomas is tested on are
  # asked for first; a machine with 3.12 and 3.14 gets 3.12 and one with only 3.14 gets that.
  foreach ($cmd in @(Get-Command py -All -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' })) {
    foreach ($flag in @('-3.13', '-3.12', '-3.11', '-3.10', '-3')) {
      if ($cmd.Source -and (Test-PythonRuns -Path $cmd.Source -LauncherArgs @($flag))) { return @{ Kind = "py"; Path = $cmd.Source; Flag = $flag } }
    }
  }
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

function Ensure-ThomasProtocolRegistration {
  # Writes HKCU (your Windows account), and used to on every launch, unannounced. Now it
  # writes once, when no handler exists or the registered script is gone, and says so.
  if ($NoProtocolHandler) { return }
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

    $existing = ''
    $existingKey = Get-Item -LiteralPath $commandKey -ErrorAction SilentlyContinue
    if ($existingKey) { $existing = [string]$existingKey.GetValue('') }
    if ($existing -and -not $RegisterProtocol) {
      # Another program's handler, or a copy of Thomas that still works, stays.
      $registered = [regex]::Match($existing, '(?i)-File\s+"([^"]*run-ui\.ps1)"')
      if (-not $registered.Success) { return }
      if (Test-Path -LiteralPath $registered.Groups[1].Value) { return }
    }

    Write-Host '[thomas] Registering the thomas:// link handler for your Windows account (HKCU\Software\Classes\thomas).'
    Write-Host '[thomas] Skip it with -NoProtocolHandler; remove it with: reg delete HKCU\Software\Classes\thomas /f'
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

function Get-LocalThomasVersion {
  # Read the literal out of thomas/__init__.py rather than booting a Python
  # interpreter for one string; importing the package to print its version cost
  # roughly a second of the launch every single time.
  try {
    $initPath = Join-Path $Root "thomas\__init__.py"
    if (Test-Path $initPath) {
      $initText = [System.IO.File]::ReadAllText($initPath, [System.Text.Encoding]::UTF8)
      $m = [regex]::Match($initText, '(?m)^__version__\s*=\s*["'']([^"'']+)["'']')
      if ($m.Success) { return $m.Groups[1].Value.Trim() }
    }
  } catch { }
  return ""
}

function ConvertTo-ComparablePath([string]$Path) {
  if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
  try { $Path = [System.IO.Path]::GetFullPath($Path) } catch { }
  return $Path.Trim().TrimEnd('\', '/').Replace('/', '\').ToLowerInvariant()
}

function Get-LocalGitCommit {
  # The commit this copy is at, as /api/health names the server's (8 characters), or
  # "" when git or a repository is not there. An installed copy has none to compare.
  $ErrorActionPreference = 'Continue'
  try {
    $git = Get-CommandPathAny @('git', 'git.exe')
    if (-not $git) { return '' }
    $out = & $git -C $Root rev-parse --short=8 HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { return '' }
    return ([string]($out | Select-Object -First 1)).Trim()
  } catch { return '' }
}

function Get-ThomasBuildLabel($Instance) {
  # "v1.2.3 dev@abcd1234+dirty, C:\path": build_info.build_label plus where it runs from.
  $label = 'v' + $Instance.Version
  if ($Instance.Branch) { $label += ' ' + $Instance.Branch }
  if ($Instance.Commit) { $label += '@' + $Instance.Commit }
  if ($Instance.Dirty) { $label += '+dirty' }
  if ($Instance.Root) { $label += ', ' + $Instance.Root }
  if ($Instance.Status -eq 'degraded') { $label += ' (reporting degraded)' }
  return $label
}

function Get-ThomasRunningInstance {
  # A Thomas server answering /api/health on this port, or $null. Identity comes from the payload,
  # not from the port being busy: version, status, and the build block (root, commit, branch, dirty)
  # that tells two copies on one version apart. A server deep in a Build is slow, so the timeout is long. Broken: degraded for a reason a restart can change; model_auth (no sign-in yet) is not one, the app shows it in chat.
  param([Parameter(Mandatory = $true)][int]$P)
  if (-not (Test-PortListening $P)) { return $null }
  try {
    $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/health" -f $P) -UseBasicParsing -TimeoutSec 10 -Method Get -ErrorAction Stop
    $health = $resp.Content | ConvertFrom-Json
  } catch {
    return $null
  }
  $version = [string]$health.version
  $status = [string]$health.status
  if (-not $version -or $status -notin @('ok', 'degraded')) { return $null }
  $build = $health.build
  return [pscustomobject]@{
    Version = $version
    Status = $status
    Broken = ($status -eq 'degraded' -and (@($health.degraded | Where-Object { $_ -ne 'model_auth' }).Count -gt 0 -or @($health.degraded).Count -eq 0))
    Root = [string]$build.root
    Commit = [string]$build.commit
    Branch = [string]$build.branch
    Dirty = ($build.dirty -eq $true)
    UptimeSec = $(try { [double]$health.uptime_s } catch { 0 })
  }
}

function Test-CodeNewerThanServer([string]$CodeRoot, [double]$UptimeSec) {
  # A server reads its Python and thomas.toml once, when it starts: a .py under thomas\ or
  # a thomas.toml written after that (now minus the uptime /api/health reports) is not loaded.
  if (-not $CodeRoot -or $UptimeSec -le 0) { return $false }
  try {
    $startedUtc = [DateTime]::UtcNow.AddSeconds(-$UptimeSec)
    $files = @([System.IO.Directory]::EnumerateFiles((Join-Path $CodeRoot 'thomas'), '*.py', 'AllDirectories')) + (Join-Path $CodeRoot 'thomas.toml')
    foreach ($file in $files) {
      if ([System.IO.File]::GetLastWriteTimeUtc($file) -gt $startedUtc) { return $true }  # a missing file reads as 1601
    }
  } catch { }
  return $false
}

function Get-ThomasActiveRuns {
  # Build runs the server on this port is working on right now, taken from the same
  # registry api_server_restart consults before it agrees to restart. Known is $false when
  # the server would not say (timeout, refusal, an answer with no "running"). A 404 is an
  # answer: a server with no such route predates Build, so it has no run to cut off.
  param([Parameter(Mandatory = $true)][int]$P)
  $unknown = [pscustomobject]@{ Known = $false; Count = 0 }
  try {
    $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/evolve/agent/status" -f $P) -UseBasicParsing -TimeoutSec 10 -Method Get -ErrorAction Stop
    $status = $resp.Content | ConvertFrom-Json
  } catch {
    $http = 0; try { $http = [int]$_.Exception.Response.StatusCode.value__ } catch { }
    if ($http -eq 404) { return [pscustomobject]@{ Known = $true; Count = 0 } }
    return $unknown
  }
  if ($null -eq $status -or $null -eq $status.PSObject.Properties['running']) { return $unknown }
  $count = if ($status.runs) { @($status.runs).Count } else { 0 }
  if (($status.running -eq $true -or $status.recording -eq $true) -and $count -eq 0) { $count = 1 }
  return [pscustomobject]@{ Known = $true; Count = $count }
}

function Get-ExistingServerPlan {
  # What to do about a server already on the port: 'start' (nothing usable there); 'attach' (use
  # it: this copy and current, or not but mid-Build or would not say, so left running, Left);
  # 'replace' (asked for, or not this copy or out of date with no Build running); 'refuse'
  # (replacing was asked for, a Build runs). This copy: same root and version, and same commit
  # when both know it. Current: not started from a dirty tree, no .py or thomas.toml written since.
  param(
    [Parameter(Mandatory = $true)][int]$P,
    [string]$LocalVersion = "",
    [string]$LocalRoot = "",
    [switch]$ReplaceIt
  )
  $running = Get-ThomasRunningInstance -P $P
  if ($null -eq $running) {
    $message = if (Test-PortListening $P) { "Port {0} is in use, but nothing there answered /api/health as Thomas within 10 seconds. A listener that looks like a Thomas server and does not answer is stopped and replaced, which ends any Build it is running; any other program there is left alone." -f $P } else { '' }
    return [pscustomobject]@{ Action = 'start'; Message = $message }
  }
  $label = Get-ThomasBuildLabel $running; $localCommit = ''; $isOther = $false
  if (($running.Root -and $LocalRoot -and (ConvertTo-ComparablePath $running.Root) -ne (ConvertTo-ComparablePath $LocalRoot)) -or ($LocalVersion -and $LocalVersion -ne $running.Version)) {
    $isOther = $true
  } elseif ($running.Commit) {
    $localCommit = Get-LocalGitCommit
    $isOther = ($localCommit -and -not ($localCommit.StartsWith($running.Commit) -or $running.Commit.StartsWith($localCommit)))
  }
  $isStale = -not $isOther -and ($running.Dirty -or (Test-CodeNewerThanServer $LocalRoot $running.UptimeSec))
  # The full command with this copy's path, which works from any folder: a bare .ps1 is refused by the default execution policy.
  $restart = ('powershell -NoProfile -ExecutionPolicy Bypass -File "{0}\scripts\run-ui.ps1" -Restart -Port {1}' -f $LocalRoot, $P)
  if (-not ($isOther -or $isStale) -and -not $ReplaceIt) {
    $message = "Using the Thomas already running on port {0} ({1}). To replace it run: {2}" -f $P, $label, $restart
    return [pscustomobject]@{ Action = 'attach'; Degraded = $running.Broken; Message = $message }
  }
  $localLabel = Get-ThomasBuildLabel ([pscustomobject]@{ Version = $LocalVersion; Commit = $localCommit; Root = $LocalRoot })
  $why = if ($isOther) { "is not this copy ($localLabel)" } else { 'is out of date (started with uncommitted changes, or before the code or thomas.toml here last changed)' }
  $active = Get-ThomasActiveRuns -P $P
  if ($active.Count -gt 0) {
    if ($ReplaceIt) { return [pscustomobject]@{ Action = 'refuse'; Other = $isOther; Message = ("Thomas on port {0} is running {1} Build run(s), so it was left running. Wait for it to finish, then try again." -f $P, $active.Count) } }
    $message = "The Thomas on port {0} ({1}) {2} and is running {3} Build run(s), so it was left running and is what opens now. Wait for it to finish, then run: {4}" -f $P, $label, $why, $active.Count, $restart
    return [pscustomobject]@{ Action = 'attach'; Left = $true; Other = $isOther; Message = $message }
  }
  if (-not $active.Known) {
    if ($ReplaceIt) { return [pscustomobject]@{ Action = 'replace'; Other = $isOther; Message = ("Thomas on port {0} would not say whether a Build is running; going ahead as you asked." -f $P) } }
    $message = "The Thomas on port {0} ({1}) {2} and would not say whether a Build is running, so it was left running and is what opens now. To replace it run: {3}" -f $P, $label, $why, $restart
    return [pscustomobject]@{ Action = 'attach'; Left = $true; Other = $isOther; Message = $message }
  }
  $message = if ($ReplaceIt) { '' } else { "Replacing the Thomas on port {0} ({1}); it {2}." -f $P, $label, $why }
  return [pscustomobject]@{ Action = 'replace'; Other = $isOther; Message = $message }
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

  Write-Host "[thomas] Python 3.10 or newer was not found. Installing Python with winget (3.11, or 3.12 if that fails; it is added to your PATH)..."
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

  # Cheap check first. Get-NetTCPConnection stays below because killing the old
  # server needs its OwningProcess, which the .NET listener table does not carry
  # - but on the common path (nothing listening on this port) we now answer in
  # ~3ms instead of paying ~1s for a connection object we would throw away.
  if (-not (Test-PortListening $P)) {
    if ($stoppedAny) { Start-Sleep -Milliseconds 500 }
    return $stoppedAny
  }

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

function Test-VenvValid {
  param([string]$VenvRoot)

  $cfg = Join-Path $VenvRoot "pyvenv.cfg"
  $py = Join-Path $VenvRoot "Scripts\\python.exe"
  return ((Test-Path $cfg) -and (Test-Path $py))
}

function Enter-LaunchLock {
  # One launch of this copy at a time: a second double-click waits for the first, then
  # finds Thomas running and uses it instead of racing it for the port. The lock is a file
  # this process holds open, which Windows frees if it dies. $null: it could not be taken.
  param([int]$WaitSec = 600)
  $lockPath = Join-Path $Root 'runtime\launch.lock'; $deadline = (Get-Date).AddSeconds($WaitSec); $told = $false
  while ($true) {
    try {
      New-Item -ItemType Directory -Force -Path (Split-Path $lockPath) | Out-Null
      return [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
      # Only a lock another launch holds (Win32 32 or 33) is worth waiting for; a full disk or a missing folder is not.
      if (($_.Exception.HResult -band 0xFFFF) -notin @(32, 33)) { return $null }
      if ((Get-Date) -ge $deadline) { Write-Host ("[thomas] Another launch is still going after {0} seconds; continuing without waiting for it." -f $WaitSec); return $null }
      if (-not $told) { Write-Host "[thomas] Another launch of Thomas is still starting; waiting for it to finish."; $told = $true }
      Start-Sleep -Milliseconds 500
    } catch { return $null }
  }
}

function Get-RecordedPort {
  # The port this copy's Thomas last started on; it moves up from -Port when that is busy.
  # 0: none recorded, -Port itself, or a -Port that was named (it is never second-guessed).
  if ($PortNamed) { return 0 }
  try { $p = [int](Get-Content -LiteralPath (Join-Path $Root 'runtime\thomas.port') -TotalCount 1 -ErrorAction Stop) } catch { return 0 }
  if ($p -lt 1024 -or $p -gt 65535 -or $p -eq $Port) { return 0 }
  return $p
}

function Invoke-ExistingServerGate {
  # Acts on Get-ExistingServerPlan before anything is written or installed. Returns the
  # exit code when the launch ends here (an existing Thomas was used or left alone, or
  # -Stop was asked for: 5 none found, 6 one would not stop), or $null when it should go
  # on and start a server. -Again: the same question a second time, so a replacement
  # already announced is not announced twice. The recorded port is asked about too, but only a Thomas that is this copy there is acted on.
  param([switch]$Again)
  $ask = @{ LocalVersion = (Get-LocalThomasVersion); LocalRoot = $Root; ReplaceIt = [bool]($Restart -or $Stop) }
  $plan = Get-ExistingServerPlan -P $Port @ask
  $moved = Get-RecordedPort
  $alt = if ($moved -and ($Stop -or $plan.Action -eq 'start')) { Get-ExistingServerPlan -P $moved @ask }
  if ($alt -and ($alt.Other -or ($alt.Action -eq 'start' -and (Test-PortListening $moved)))) { $alt = $null }
  if ($alt -and $alt.Action -ne 'start' -and -not $Stop) { $plan = $alt; $script:Port = $moved }
  if ($plan.Message -and -not ($Again -and $plan.Action -in @('replace', 'start'))) { Write-Host ("[thomas] " + $plan.Message) }

  if ($Stop) {
    if ($alt -and $alt.Action -eq 'refuse') { Write-Host ("[thomas] " + $alt.Message) }
    if ($plan.Action -eq 'refuse' -or ($alt -and $alt.Action -eq 'refuse')) { return 3 }
    $ports = @($Port, $(if ($alt) { $moved }) | Where-Object { $_ })
    $ended = @($ports | Where-Object { Stop-ThomasServerOnPort $_ })
    # Stop-Process says nothing when it fails, so a Thomas still there is found by looking.
    $stuck = @($ports | Where-Object { (Test-PortListening $_) -and (($ended -contains $_) -or (Get-ThomasRunningInstance -P $_)) })
    if ($stuck) { Write-Host ("[thomas] Thomas on port " + ($stuck -join ' and ') + " could not be stopped."); return 6 }
    Write-Host ("[thomas] " + $(if ($ended) { "Stopped Thomas on port " + ($ended -join ' and ') + "." } else { "No Thomas was found on port " + ($ports -join ' or ') + "." }))
    return $(if ($ended) { 0 } else { 5 })
  }
  if ($plan.Action -notin @('attach', 'refuse')) { return $null }

  if ($Tray) { Write-Host "[thomas] -Tray was not started: Thomas is already running. Add -Restart to replace it with the tray agent." }
  if (-not $NoBrowser) {
    $existingUrl = Get-ThomasLaunchUrl -BaseUrl ("http://127.0.0.1:{0}/" -f $Port) -RequestedDeepLink $DeepLink
    try { Start-Process $existingUrl | Out-Null } catch { }
  }
  if ($plan.Action -eq 'refuse') { return 3 }
  # 4: a Thomas is open, but it is not this copy or is out of date; 7: it is this copy but reports degraded. launch-thomas.vbs says so.
  if ($plan.Left) { return 4 }
  if ($plan.Degraded) { return 7 }
  return 0
}

function Ensure-ThomasVenv {
  # A system Python is only needed to create .venv; a working .venv never asks for one.
  # Returns an exit code when .venv cannot be made, $null when it is there.
  if (Test-VenvValid $VenvRoot) { return $null }
  $SysPy = Ensure-SystemPython
  if (-not $SysPy) {
    Write-Host "[thomas] ERROR: Python 3.10 or newer was not found, and it could not be installed automatically."
    Write-Host "[thomas] Install Python 3.10 or newer from https://www.python.org/downloads/ and try again."
    return 2
  }
  if (Test-Path $VenvRoot) {
    Write-Host "[thomas] Existing .venv is incomplete. Recreating it..."
    Remove-Item -Recurse -Force $VenvRoot -ErrorAction Stop
  }
  Write-Host "[thomas] Creating venv in .venv..."
  if ($SysPy.Kind -eq "py") {
    & $SysPy.Path $SysPy.Flag -m venv .venv | Out-Host
  } else {
    & $SysPy.Path -m venv .venv | Out-Host
  }

  if (-not (Test-VenvValid $VenvRoot)) {
    Write-Host "[thomas] ERROR: venv creation failed."
    return 2
  }
  return $null
}

$LaunchLock = $null
if (-not $Stop) { $LaunchLock = Enter-LaunchLock }

# A Thomas server that already answers on this port is used, left alone or replaced
# here, before anything is written or installed: stopping one ends whatever it is
# in the middle of (a second double-click, a thomas:// link click).
$gateExit = Invoke-ExistingServerGate
if ($null -ne $gateExit) { exit $gateExit }

Ensure-ThomasProtocolRegistration

$VenvRoot = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvRoot "Scripts\\python.exe"
$venvExit = Ensure-ThomasVenv
if ($null -ne $venvExit) { exit $venvExit }

function Ensure-Installed {
  if ($NoInstall) { return }

  # Install only if missing deps (keeps repeat runs fast).
  $probe = Invoke-NativeQuiet $VenvPy @("-c", "import aiohttp, httpx")
  if ($probe -ne 0) {
    Write-Host "[thomas] Installing runtime dependencies (editable) ..."
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server]", "--disable-pip-version-check")
    if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }
    return
  }

  # No `pip show thomas-ai` probe here: the import probe above already proves the
  # environment is installed, and pip show spent a whole subprocess (~0.8s on
  # every launch) confirming what that import implies.
}

function Find-FreePort([int]$Preferred) {
  for ($p = $Preferred; $p -le ($Preferred + 25); $p++) {
    if (-not (Test-PortListening $p)) { return $p }
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
    $listening = [bool](Test-PortListening $P)
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
  # Never throw a Notepad window in the owner's face. Thomas is an app, and an
  # app that fails to start does not open a text editor about it. The path is
  # written above for anyone who wants the detail.
  if (-not $recovered) {
    Write-Host "[thomas] Boot did not recover. The report path above has the detail."
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
      "--relaunch",
      # The window is hidden, so the rescue must never wait for typed input:
      # without this it ends at "Press Enter" and waits for good.
      "--no-interactive"
      # Hidden: a rescue is Thomas's business, not a console the owner must
      # watch. Without this a PowerShell window pops up on every rescue.
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
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

Ensure-Installed

function Invoke-FirstRunQuickSetup {
  if ($NoInstall) { return }

  $statusPath = Join-Path $Root "runtime\\setup\\last_setup.txt"
  if (Test-Path $statusPath) {
    if ($InstallTools) { Write-Host "[thomas] -InstallTools only applies to a first launch, and first-run setup has already run. Run setup.cmd to install Node.js, the Codex CLI or Ollama." }
    return
  }

  $setupScript = Join-Path $Root "scripts\\setup.ps1"
  if (-not (Test-Path $setupScript)) { return }

  Write-Host "[thomas] First launch detected. Running quick setup: it picks a default model in thomas.toml, adds Desktop and Start Menu shortcuts, and runs npm install for the desktop shell if Node.js is already installed."
  $setupArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setupScript, '-Easy', '-NoPrompt', '-SkipInstall', '-SkipDoctor')
  if ($InstallTools -or $env:THOMAS_AUTO_INSTALL_TOOLS -eq '1') {
    Write-Host "[thomas] Tool installs are on: setup may install Node.js, the Codex CLI and Ollama with winget and npm."
    $setupArgs += '-AutoInstallTools'
  } else {
    Write-Host "[thomas] Not installing Node.js, the Codex CLI or Ollama. Without Node.js the desktop shell is not installed, so web tabs stay blank on sites that refuse framing. Run setup.cmd (or run-ui with -InstallTools on a first launch) if you want them."
  }
  $code = 0
  try {
    & powershell @setupArgs
    $code = $LASTEXITCODE
  } catch {
    $code = 1
  }

  if ($code -ne 0) {
    Write-Host "[thomas] Quick setup did not complete cleanly. You can continue and run setup.cmd later."
  }
}

Invoke-FirstRunQuickSetup

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

  if ($defaultModel -eq "openai_codex") {
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

  if (Test-PortListening 11434) { return }

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

# Ã¢â€â‚¬Ã¢â€â‚¬ Start fresh Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# A current copy was reused above. Asked again just before the stop: setup takes minutes, and a Build may have started.
# Start the requested Thomas surface from this working tree without
# enumerating or stopping unrelated listeners on other ports.
# Stop-ThomasServerOnPort also stops a tray agent bound to this exact port.
$lastGate = Invoke-ExistingServerGate -Again
if ($null -ne $lastGate) { exit $lastGate }
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
# Where this copy's Thomas is, for -Stop and the next launch: the default port was busy and it moved up. Not for a named -Port.
if (-not $PortNamed) { try { Set-Content -LiteralPath (Join-Path $Root 'runtime\thomas.port') -Value $Port -Encoding Ascii -ErrorAction Stop } catch { } }

# Show what version we're about to start so the user can confirm it's current.
$startingVersion = Get-LocalThomasVersion
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

  # Idle self-improvement engines (code-issue, self-upgrade, UI-workflow,
  # local-agent, workspace-sync) make continuous background LLM calls that
  # burn the ChatGPT subscription while nobody is using Thomas (observed:
  # one POST to chatgpt.com every ~19s, 24/7). Default them OFF for
  # launcher-started servers until interactive use is reliable. To re-enable,
  # set the variable to "1" in the shell before running run-ui.
  foreach ($quietVar in @(
      'THOMAS_CODE_ISSUE_ENGINE_ENABLED',
      'THOMAS_SELF_UPGRADE_ENGINE_ENABLED',
      'THOMAS_UI_WORKFLOW_ENGINE_ENABLED',
      'THOMAS_LOCAL_AGENT_ENGINE_ENABLED',
      'THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED',
      'THOMAS_WORKSPACE_SYNC_AUTO_PUSH')) {
    if (-not (Test-Path "Env:$quietVar")) { Set-Item "Env:$quietVar" '0' }
  }

  $logDir = Join-Path $Root 'runtime\logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $stdoutLog = Join-Path $logDir 'server_stdout.log'
  $stderrLog = Join-Path $logDir 'server_stderr.log'

  try {
    # Hidden: both streams go to the logs above, so the console window this would
    # otherwise open is empty, and closing it stops Thomas mid-session.
    $proc = Start-Process `
      -FilePath $VenvPy `
      -ArgumentList @('-m', 'thomas.server', '--host', $BindAddress, '--port', "$ServerPort") `
      -WorkingDirectory $Root `
      -WindowStyle Hidden `
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
    Write-Host "[thomas] Installing tray icon dependencies..."
    Invoke-Native $VenvPy @("-m", "pip", "install", "pystray", "pillow", "win10toast", "--quiet") | Out-Null
  }

  $startupWatchProc = Start-ThomasStartupRecoveryWatch
  $watchProc = Start-MonolithWatch
  # The tray agent runs for as long as Thomas does; another launch must not wait on it.
  if ($LaunchLock) { $LaunchLock.Dispose() }
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
  Write-Host "[thomas] Starting server directly (no tray icon). It has no window; to stop it run: powershell -NoProfile -ExecutionPolicy Bypass -File `"$Root\scripts\run-ui.ps1`" -Stop -Port $Port"
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
