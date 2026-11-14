"""start-tray-agent.ps1 stops the Thomas tray agent and server on its own port, and only there.

The launcher's stop functions run under Windows PowerShell 5.1 against a made-up
process table: Get-CimInstance, Get-NetTCPConnection and Stop-Process are
stand-ins, and Stop-Process only records an id and drops it from the table, so no
real process is listed or stopped. The trees mirror what Windows builds: a venv's
python.exe starts the real interpreter as a child with the same command line.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.tray_support import functions, needs_powershell, run_powershell, script_default_port, script_source

_STUBS = r"""
function Write-Host { }
$script:Stopped = @()
$script:Procs = @{}
$script:Listeners = @{}
function Add-Proc([int]$ProcessId, [string]$Name, [string]$Command, [int]$Parent) {
    $script:Procs[$ProcessId] = [pscustomobject]@{
        ProcessId = $ProcessId; Name = $Name; CommandLine = $Command; ParentProcessId = $Parent
    }
}
function Get-NetTCPConnection {
    [CmdletBinding()] param([int]$LocalPort, [string]$State)
    $owner = $script:Listeners[$LocalPort]
    if ($owner -and $script:Procs.ContainsKey([int]$owner)) { [pscustomobject]@{ OwningProcess = [int]$owner } }
}
function Get-CimInstance {
    [CmdletBinding()] param([Parameter(Position = 0)][string]$ClassName, [string]$Filter)
    if ($Filter -match 'ProcessId=(\d+)') {
        $script:Procs[[int]$Matches[1]]
    } else {
        $script:Procs.Values | Where-Object { $_.Name -in 'python.exe', 'pythonw.exe' } | Sort-Object ProcessId
    }
}
function Stop-Process {
    [CmdletBinding()] param([int]$Id, [switch]$Force)
    $script:Stopped += $Id
    $script:Procs.Remove($Id)
}
foreach ($name in 'Stop-Process', 'Get-CimInstance', 'Get-NetTCPConnection') {
    # The ids in these tables are made up; a real Stop-Process on one could end a real process.
    if ((Get-Command $name).CommandType -ne 'Function') { throw "$name is not a stand-in" }
}
Add-Proc 4 'explorer.exe' 'C:\Windows\explorer.exe' 1
"""

_VENV = r"C:\r\.venv\Scripts"


def _stopped(tmp_path: Path, setup: str, *ports: int) -> list[str]:
    """Run Stop-ThomasOnPort once per port; each answer is the ids stopped, in order."""
    body = "\n".join(
        f"$script:Stopped = @(); Stop-ThomasOnPort -ServerPort {port}; Write-Output ('RESULT:' + ($script:Stopped -join ','))"
        for port in ports
    )
    names = ("Test-ThomasCommand", "Get-ThomasCommandPort", "Test-ThomasProcessOnPort")
    script = "\n".join([_STUBS, functions(*names, "Stop-ThomasListenerOnPort", "Stop-ThomasOnPort"), setup, body])
    return run_powershell(tmp_path, script)


@needs_powershell
def test_only_the_processes_serving_this_port_are_stopped(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc 10 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent --port 22040' 4
Add-Proc 11 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1 --port 22040' 10
Add-Proc 20 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent --port 22041' 4
Add-Proc 21 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1 --port 22041' 20
Add-Proc 30 'python.exe' 'python.exe -m http.server --port 22040' 4
$script:Listeners[22040] = 11
$script:Listeners[22041] = 21
"""

    # The tray and server that name 22040 go; 22041's pair and a non-Thomas server stay.
    assert _stopped(tmp_path, setup, 22040) == ["10,11"]


@needs_powershell
def test_a_server_with_no_port_flag_is_found_by_its_socket(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc 40 'python.exe' '{_VENV}\python.exe -m thomas.server' 4
Add-Proc 41 'python.exe' 'python.exe -m http.server 22043' 4
$script:Listeners[22042] = 40
$script:Listeners[22043] = 41
"""

    # 22042: a Thomas server that names no port. 22043: not Thomas. 22044: nothing listens.
    assert _stopped(tmp_path, setup, 22042, 22043, 22044) == ["40", "", ""]


@needs_powershell
def test_the_thomas_processes_above_a_listening_server_are_stopped_top_first(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc 60 'python.exe' '{_VENV}\python.exe -m thomas serve' 4
Add-Proc 61 'python.exe' '{_VENV}\python.exe -m thomas serve' 60
Add-Proc 62 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 61
Add-Proc 63 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 62
$script:Listeners[22045] = 63
"""

    # The listener's parent is the venv launcher, and the process that would start it
    # again is above that. Stopping only the immediate parent left the tray running.
    assert _stopped(tmp_path, setup, 22045) == ["60,61,62,63"]


@needs_powershell
def test_a_tray_started_without_a_port_serves_the_default_port(tmp_path: Path) -> None:
    default = script_default_port()
    setup = rf"""
Add-Proc 50 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent' 4
Add-Proc 51 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent' 50
Add-Proc 52 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 51
Add-Proc 53 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 52
$script:Listeners[{default}] = 53
"""

    # `python -m thomas.tray_agent` with no --port is the documented way to start it.
    assert _stopped(tmp_path, setup, default) == ["50,51,52,53"]


@needs_powershell
def test_a_tray_for_the_default_port_is_left_alone_when_stopping_another_port(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc 50 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent' 4
Add-Proc 51 'pythonw.exe' '{_VENV}\pythonw.exe -m thomas.tray_agent' 50
Add-Proc 52 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 51
Add-Proc 53 'python.exe' '{_VENV}\python.exe -m thomas.server --host 127.0.0.1' 52
$script:Listeners[22046] = 53
"""

    # The server on 22046 goes with its launcher; the tray above them serves the default port.
    assert _stopped(tmp_path, setup, 22046) == ["52,53"]


@needs_powershell
def test_the_climb_stops_at_a_process_that_is_not_this_ports_thomas(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc 70 'powershell.exe' 'powershell.exe -File C:\r\scripts\run-ui.ps1' 4
Add-Proc 71 'python.exe' '{_VENV}\python.exe -m thomas.server' 70
Add-Proc 72 'python.exe' '{_VENV}\python.exe -m thomas.server --port 22999' 4
Add-Proc 73 'python.exe' '{_VENV}\python.exe -m thomas.server' 72
$script:Listeners[22047] = 71
$script:Listeners[22048] = 73
"""

    # 22047's parent is a shell. 22048's parent is Thomas, but names another port.
    assert _stopped(tmp_path, setup, 22047, 22048) == ["71", "73"]


@needs_powershell
def test_the_starter_never_stops_itself(tmp_path: Path) -> None:
    setup = rf"""
Add-Proc $PID 'python.exe' '{_VENV}\python.exe -m thomas.server --port 22049' 4
Add-Proc 80 'python.exe' '{_VENV}\python.exe -m thomas.server' 4
$script:Listeners[22049] = $PID
"""
    own_port = _stopped(tmp_path, setup, 22049)

    setup_above = rf"""
Add-Proc $PID 'python.exe' '{_VENV}\python.exe -m thomas.server' 4
Add-Proc 81 'python.exe' '{_VENV}\python.exe -m thomas.server' $PID
$script:Listeners[22050] = 81
"""
    above = _stopped(tmp_path, setup_above, 22050)

    # Its own process is neither named by --port nor the listener, and never an ancestor to climb.
    assert (own_port, above) == ([""], ["81"])


def test_the_main_flow_stops_what_serves_its_own_port_before_the_agent_starts() -> None:
    source = script_source()

    calls = re.findall(r"^Stop-ThomasOnPort -ServerPort \$Port\r?$", source, re.M)
    assert len(calls) == 1
    # The function enumerates the port's processes, then the listener.
    body = functions("Stop-ThomasOnPort")
    assert "Test-ThomasProcessOnPort -CommandLine ([string]$proc.CommandLine) -ServerPort $ServerPort" in body
    assert "Stop-ThomasListenerOnPort -ServerPort $ServerPort" in body
    assert source.index("function Stop-ThomasOnPort") < source.index("Stop-ThomasOnPort -ServerPort $Port")
    assert source.index("Stop-ThomasOnPort -ServerPort $Port") < source.index("& $VenvPy -m thomas.tray_agent")
