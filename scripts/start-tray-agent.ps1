<#
.SYNOPSIS
    Start Thomas Tray Agent (24/7 background process with system tray icon)

.DESCRIPTION
    This script starts the Thomas Tray Agent which:
    - Runs as a hidden background process
    - Shows a system tray icon with status
    - Auto-starts the Thomas server
    - Monitors and auto-restarts if crashed
    - Provides friendly notifications

.PARAMETER Port
    Server port (default: 8899)

.PARAMETER InstallStartup
    Install auto-start with Windows boot

.PARAMETER UninstallStartup
    Remove auto-start with Windows boot

.EXAMPLE
    .\start-tray-agent.ps1
    Start the tray agent on default port

.EXAMPLE
    .\start-tray-agent.ps1 -InstallStartup
    Install tray agent to start automatically with Windows
#>

param(
    [int]$Port = 8899,
    [switch]$InstallStartup,
    [switch]$UninstallStartup
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[thomas] ERROR: venv not found. Run run-ui.ps1 first to set up."
    exit 2
}

# Handle install/uninstall startup
if ($InstallStartup) {
    Write-Host "[thomas] Installing auto-start with Windows..."
    $TaskName = "ThomasTrayAgent"
    $ScriptPath = Join-Path $Root "scripts\start-tray-agent.ps1"
    
    # Remove existing task if present
    try {
        schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
    } catch { }
    
    # Create new task
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Port $Port"
    $Trigger = New-ScheduledTaskTrigger -AtLogon
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    
    Write-Host "[thomas] Auto-start installed. Thomas will start automatically on next login."
    exit 0
}

if ($UninstallStartup) {
    Write-Host "[thomas] Removing auto-start..."
    $TaskName = "ThomasTrayAgent"
    try {
        schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
        Write-Host "[thomas] Auto-start removed."
    } catch {
        Write-Host "[thomas] Auto-start was not installed."
    }
    exit 0
}

# ── Kill ALL existing Thomas instances before starting ──────────────
# Always start fresh so we run the current version, not a stale one.
Write-Host "[thomas] Stopping any existing Thomas instances..."
try {
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $pyProcs) {
        $procCmd = [string]$proc.CommandLine
        if ($procCmd -and ($procCmd -match '(?i)-m\s+thomas(\.server|\.tray_agent)\b' -or $procCmd -match '(?i)\bthomas(\.exe)?\s+serve\b')) {
            $procId = [int]$proc.ProcessId
            if ($procId -gt 0 -and $procId -ne $PID) {
                Write-Host ("[thomas] Stopping existing Thomas process (pid {0})" -f $procId)
                try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch { }
            }
        }
    }
} catch { }
Start-Sleep -Milliseconds 500

# Check if pystray is installed
$PystrayCheck = & $VenvPy -c "import pystray; print('ok')" 2>$null
if ($PystrayCheck -ne "ok") {
    Write-Host "[thomas] Installing pystray for system tray support..."
    & $VenvPy -m pip install pystray pillow win10toast --quiet
}

# Start the tray agent
Write-Host "[thomas] Starting Thomas Tray Agent..."
Write-Host "[thomas] Tray icon will appear in system tray (bottom right)."
Write-Host "[thomas] Right-click tray icon for options."

& $VenvPy -m thomas.tray_agent --port $Port
