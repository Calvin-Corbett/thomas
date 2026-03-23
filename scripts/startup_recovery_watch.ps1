param(
  [Parameter(Mandatory = $true)][string]$Root,
  [Parameter(Mandatory = $true)][int]$Port,
  [string]$LaunchUrl = "",
  [string]$LaunchMode = "direct",
  [switch]$NoBrowser,
  [int]$StartupTimeoutSec = 25,
  [int]$RecoveryTimeoutSec = 90
)

$ErrorActionPreference = "Stop"
Set-Location $Root

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
    [Parameter(Mandatory = $true)][int]$TimeoutSec,
    [int]$DelayMs = 400
  )

  $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSec))
  $last = $null
  while ((Get-Date) -lt $deadline) {
    $last = Get-ThomasBootHealth -P $P
    if ($last.Ready) { return $last }
    Start-Sleep -Milliseconds ([Math]::Max(50, $DelayMs))
  }
  if ($null -eq $last) {
    $last = Get-ThomasBootHealth -P $P
  }
  return $last
}

function Open-ThomasBrowser {
  if ($NoBrowser) { return }
  if ([string]::IsNullOrWhiteSpace($LaunchUrl)) { return }
  try { Start-Process $LaunchUrl | Out-Null } catch { }
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

function Get-BootDoctorRuntimeDir {
  return (Join-Path $Root "runtimeoot_doctor")
}

function Write-BootDoctorDegradedStatus {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][int]$DiagPort
  )

  $diagDir = Get-BootDoctorRuntimeDir
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  $statusPath = Join-Path $diagDir 'rescue_status.json'
  $payload = [ordered]@{
    status = 'degraded'
    phase = 'repairing'
    message = 'Thomas launched in a degraded state while Boot Doctor investigates.'
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

function Write-StartupContext {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$HealthStatus,
    [string]$StdErrTail = "",
    [string[]]$StartupLogPaths = @()
  )

  $diagDir = Get-BootDoctorRuntimeDir
  New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $path = Join-Path $diagDir ("startup_context_{0}.json" -f $stamp)
  $payload = [ordered]@{
    created_at_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    reason = $Reason
    attempted_launch_mode = $LaunchMode
    target_port = [int]$Port
    current_health_status = $HealthStatus
    ever_healthy_during_boot = $false
    startup_timeout_sec = [int]$StartupTimeoutSec
    recovery_timeout_sec = [int]$RecoveryTimeoutSec
    launch_url = $LaunchUrl
    stderr_tail = [string]$StdErrTail
    startup_log_paths = @($StartupLogPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $path -Encoding UTF8
  return $path
}

function Start-BootDoctorBackgroundRepair {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][int]$DiagPort
  )

  $bootDoctorScript = Join-Path $Root "scriptsootdoctor.ps1"
  if (-not (Test-Path $bootDoctorScript)) {
    return $null
  }

  return Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $bootDoctorScript,
    "report",
    "--force",
    "--port", "$DiagPort",
    "--reason", $Reason,
    "--relaunch"
  ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
}

function Start-BootDoctorRescue {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ContextPath
  )

  $bootDoctorScript = Join-Path $Root "scriptsootdoctor.ps1"
  if (-not (Test-Path $bootDoctorScript)) {
    return $null
  }

  return Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $bootDoctorScript,
    "rescue",
    "--force",
    "--port", "$Port",
    "--reason", $Reason,
    "--startup-context", $ContextPath,
    "--relaunch"
  ) -WorkingDirectory $Root -PassThru
}

$startupState = Wait-ThomasBootHealth -P $Port -TimeoutSec $StartupTimeoutSec
if ($startupState.Ready) {
  if ($startupState.Severity -eq 'degraded') {
    $reason = "Startup watchdog: Thomas became available in a degraded state on port $Port."
    Write-BootDoctorDegradedStatus -Reason $reason -DiagPort $Port
    try { Start-BootDoctorBackgroundRepair -Reason $reason -DiagPort $Port | Out-Null } catch { }
  }
  Open-ThomasBrowser
  exit 0
}

$reason = "Startup watchdog: Thomas never became ready on port $Port."
$startupLogPaths = @(
  (Join-Path $Root "runtime\logs\server_stderr.log"),
  (Join-Path $Root "runtime\logs\server_stdout.log")
) | Where-Object { Test-Path $_ } | Select-Object -Unique
$stderrTail = ""
foreach ($logPath in $startupLogPaths) {
  $stderrTail = Get-FileTailText -Path $logPath
  if (-not [string]::IsNullOrWhiteSpace($stderrTail)) {
    break
  }
}
$contextPath = Write-StartupContext -Reason $reason -HealthStatus ([string]$startupState.Severity) -StdErrTail $stderrTail -StartupLogPaths $startupLogPaths
$proc = $null
try {
  $proc = Start-BootDoctorRescue -Reason $reason -ContextPath $contextPath
} catch {
}

$recoveryState = Wait-ThomasBootHealth -P $Port -TimeoutSec $RecoveryTimeoutSec
if ($recoveryState.Ready) {
  if ($recoveryState.Severity -eq 'degraded') {
    Write-BootDoctorDegradedStatus -Reason "Boot Doctor rescue restored Thomas in a degraded state on port $Port." -DiagPort $Port
  }
  Open-ThomasBrowser
  exit 0
}

if ($null -ne $proc -and -not $proc.HasExited) {
  exit 1
}

exit 1
