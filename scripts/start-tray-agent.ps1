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
    Register a per-user logon task that starts the tray agent without a console
    window. It runs as you, not elevated; nothing here asks for administrator
    rights.

.PARAMETER UninstallStartup
    Remove that logon task

.EXAMPLE
    .\start-tray-agent.ps1
    Start the tray agent on default port. Only a tray agent or server already
    bound to this port is stopped first; other ports and checkouts are untouched.

.EXAMPLE
    .\start-tray-agent.ps1 -InstallStartup
    Install tray agent to start automatically at your Windows logon
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

# The per-user logon task. It runs pythonw.exe directly (no console window, no
# PowerShell wrapper) and stays at the normal run level: the tray never needs
# elevation, so the login task must not ask for it. No time limit: the default
# stops a task after 72 hours, and this one runs all day. An earlier task of the
# same name is replaced by -Force, not deleted first. True when Windows accepted it.
function Register-TrayStartupTask {
    param([string]$RepoRoot, [int]$ServerPort, [string]$TaskName = "ThomasTrayAgent")
    try {
        $Scripts = Join-Path $RepoRoot ".venv\Scripts"
        $TaskExe = if (Test-Path (Join-Path $Scripts "pythonw.exe")) { Join-Path $Scripts "pythonw.exe" } else { Join-Path $Scripts "python.exe" }
        $Action = New-ScheduledTaskAction -Execute $TaskExe -Argument "-m thomas.tray_agent --port $ServerPort" -WorkingDirectory $RepoRoot
        $Trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
        $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
        $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
        return $true
    } catch {
        Write-Host ("[thomas] ERROR: Windows did not accept the auto-start task: {0}" -f $_.Exception.Message)
        Write-Host "[thomas] No auto-start task was created."
        return $false
    }
}

# Handle install/uninstall startup
if ($InstallStartup) {
    Write-Host "[thomas] Installing auto-start with Windows..."
    if (-not (Register-TrayStartupTask -RepoRoot $Root -ServerPort $Port)) { exit 1 }
    Write-Host "[thomas] Auto-start installed. At your next login the tray agent starts without a console window, as you (not elevated)."
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

# -- Stop the Thomas tray agent and server bound to THIS port ------------
# Start fresh so we run the current version, not a stale one. Only a process that
# serves $Port is touched: servers on other ports are somebody else's work
# (run-ui.ps1 scopes the same way).

# A command line that is a Thomas server or tray agent, whatever port it names.
function Test-ThomasCommand {
    param([string]$CommandLine)
    if (-not $CommandLine) { return $false }
    return [bool](($CommandLine -match '(?i)-m\s+thomas(\.server|\.tray_agent)\b') -or
                  ($CommandLine -match '(?i)\bthomas(\.exe)?\s+serve\b') -or
                  ($CommandLine -match '(?i)thomas[\\/]tray_agent[\\/]__main__\.py'))
}

# The port a Thomas command line serves: the one it names, else the tray agent's own
# default (thomas/tray_agent/__main__.py), so `python -m thomas.tray_agent` with no
# --port counts as 8899. 0 when it names none: a server with no --port listens on
# the configured port, which only its socket tells. -1 when the number is not a port.
function Get-ThomasCommandPort {
    param([string]$CommandLine)
    if ($CommandLine -match '(?i)--port(?:\s+|=)(\d+)\b') {
        $named = 0
        if ([int]::TryParse($Matches[1], [ref]$named)) { return $named }
        return -1
    }
    if ($CommandLine -match '(?i)-m\s+thomas\.tray_agent\b|thomas[\\/]tray_agent[\\/]__main__\.py') { return 8899 }
    return 0
}

function Test-ThomasProcessOnPort {
    param([string]$CommandLine, [int]$ServerPort)
    if (-not (Test-ThomasCommand -CommandLine $CommandLine)) { return $false }
    return ((Get-ThomasCommandPort -CommandLine $CommandLine) -eq $ServerPort)
}

# A server whose command line names no --port (one started by hand, or by an older
# tray) is found by the socket it listens on, as run-ui.ps1 does. The Thomas
# processes above it go first, top-most first, or the tray would start the server
# again. A venv's python.exe starts the real interpreter as a child with the same
# command line, so the server's parent is usually that launcher and the tray is
# above it. The climb stops at the first process that is not Thomas or that names
# another port.
function Stop-ThomasListenerOnPort {
    param([int]$ServerPort)
    foreach ($listener in @(Get-NetTCPConnection -LocalPort $ServerPort -State Listen -ErrorAction SilentlyContinue)) {
        $ownerId = [int]$listener.OwningProcess
        if ($ownerId -le 0 -or $ownerId -eq $PID) { continue }
        $owner = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ownerId) -ErrorAction SilentlyContinue
        if (-not $owner -or -not (Test-ThomasCommand -CommandLine ([string]$owner.CommandLine))) { continue }
        $above = @()
        $seen = @($ownerId, $PID)
        $nextId = [int]$owner.ParentProcessId
        while ($nextId -gt 0 -and $seen -notcontains $nextId -and $above.Count -lt 8) {
            $seen += $nextId
            $ancestor = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $nextId) -ErrorAction SilentlyContinue
            if (-not $ancestor) { break }
            $ancestorCommand = [string]$ancestor.CommandLine
            $ancestorPort = Get-ThomasCommandPort -CommandLine $ancestorCommand
            if (-not (Test-ThomasCommand -CommandLine $ancestorCommand)) { break }
            if ($ancestorPort -ne 0 -and $ancestorPort -ne $ServerPort) { break }
            $above = @($nextId) + $above
            $nextId = [int]$ancestor.ParentProcessId
        }
        foreach ($aboveId in $above) {
            Write-Host ("[thomas] Stopping the Thomas process above the server on port {0} (pid {1})" -f $ServerPort, $aboveId)
            try { Stop-Process -Id $aboveId -Force -ErrorAction SilentlyContinue } catch { }
        }
        Write-Host ("[thomas] Stopping the Thomas server listening on port {0} (pid {1})" -f $ServerPort, $ownerId)
        try { Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue } catch { }
    }
}

# Stop every Thomas tray agent and server that serves this port and nothing else.
function Stop-ThomasOnPort {
    param([int]$ServerPort)
    try {
        $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
        foreach ($proc in $pyProcs) {
            if (Test-ThomasProcessOnPort -CommandLine ([string]$proc.CommandLine) -ServerPort $ServerPort) {
                $procId = [int]$proc.ProcessId
                if ($procId -gt 0 -and $procId -ne $PID) {
                    Write-Host ("[thomas] Stopping existing Thomas process on port {0} (pid {1})" -f $ServerPort, $procId)
                    try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch { }
                }
            }
        }
        Stop-ThomasListenerOnPort -ServerPort $ServerPort
    } catch { }
}

Write-Host ("[thomas] Stopping any existing Thomas tray agent or server on port {0}..." -f $Port)
Stop-ThomasOnPort -ServerPort $Port
Start-Sleep -Milliseconds 500

# Windows PowerShell 5.1 turns anything a native command writes to stderr into a
# terminating error while $ErrorActionPreference is Stop, so these two run under
# Continue and answer with the exit code instead.
function Test-TrayIconPackages {
    param([string]$Python, [string]$Module = "pystray")
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python -c "import importlib, sys; importlib.import_module(sys.argv[1])" $Module 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Install-TrayIconPackages {
    param([string]$Python, [string[]]$Packages = @("pystray", "pillow", "win10toast"))
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python -m pip install @Packages --quiet | Out-Host
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

# Check if pystray is installed. Without it the agent still runs and serves
# Thomas, but headless: no tray icon and no notifications. Say so if the
# install does not work instead of leaving that to be discovered.
$TrayIconReady = Test-TrayIconPackages -Python $VenvPy
if (-not $TrayIconReady) {
    Write-Host "[thomas] pystray is not installed. Trying to install pystray, pillow and win10toast for the tray icon..."
    $TrayIconReady = (Install-TrayIconPackages -Python $VenvPy) -and (Test-TrayIconPackages -Python $VenvPy)
    if (-not $TrayIconReady) {
        Write-Host "[thomas] WARNING: the tray icon packages did not install (see the pip output above)."
        Write-Host "[thomas] The agent will run headless: Thomas is served, but there is no tray icon or notification."
    }
}

# Start the tray agent
Write-Host "[thomas] Starting Thomas Tray Agent..."
if ($TrayIconReady) {
    Write-Host "[thomas] Tray icon will appear in system tray (bottom right)."
    Write-Host "[thomas] Right-click tray icon for options."
}

& $VenvPy -m thomas.tray_agent --port $Port
