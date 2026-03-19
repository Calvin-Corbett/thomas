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
    [Parameter(Mandatory = $true)][int]$TimeoutSec,
    [int]$DelayMs = 400
  )

  $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSec))
  while ((Get-Date) -lt $deadline) {
    if (Test-ThomasHttpOnPort $P) { return $true }
    Start-Sleep -Milliseconds ([Math]::Max(50, $DelayMs))
  }
  return (Test-ThomasHttpOnPort $P)
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

function Write-StartupContext {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$HealthStatus,
    [string]$StdErrTail = "",
    [string[]]$StartupLogPaths = @()
  )

  $diagDir = Join-Path $Root "runtime\boot_doctor"
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

function Start-BootDoctorRescue {
  param(
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ContextPath
  )

  $bootDoctorScript = Join-Path $Root "scripts\bootdoctor.ps1"
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

if (Wait-ThomasHttpOnPort -P $Port -TimeoutSec $StartupTimeoutSec) {
  Open-ThomasBrowser
  exit 0
}

$reason = "Startup watchdog: Thomas never became healthy on port $Port."
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
$contextPath = Write-StartupContext -Reason $reason -HealthStatus "unhealthy" -StdErrTail $stderrTail -StartupLogPaths $startupLogPaths
$proc = $null
try {
  $proc = Start-BootDoctorRescue -Reason $reason -ContextPath $contextPath
} catch {
}

if (Wait-ThomasHttpOnPort -P $Port -TimeoutSec $RecoveryTimeoutSec) {
  Open-ThomasBrowser
  exit 0
}

if ($null -ne $proc -and -not $proc.HasExited) {
  exit 1
}

exit 1
