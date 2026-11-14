"""start-tray-agent.ps1 -InstallStartup asks Windows for the right task, and says when it refuses.

Register-TrayStartupTask is copied out of the launcher and run under Windows
PowerShell 5.1 with every Task Scheduler cmdlet replaced by a stand-in that records
its arguments. The real scheduler is never called: the stand-ins for `schtasks` and
the other scheduler cmdlets throw, and the probe checks that all of them are in place
before it registers anything.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.tray_support import functions, needs_powershell, run_powershell, script_source

_STUBS = r"""
$script:Said = @()
$script:Calls = @{}
$script:RegisterThrows = $false
function Write-Host { $script:Said += ($args -join ' ') }
function New-ScheduledTaskAction {
    [CmdletBinding()] param([string]$Execute, [string]$Argument, [string]$WorkingDirectory)
    $script:Calls['Action'] = $PSBoundParameters
    'action'
}
function New-ScheduledTaskTrigger {
    [CmdletBinding()] param([switch]$AtLogon, [string]$User)
    $script:Calls['Trigger'] = $PSBoundParameters
    'trigger'
}
function New-ScheduledTaskSettingsSet {
    [CmdletBinding()] param(
        [switch]$StartWhenAvailable, [switch]$DontStopOnIdleEnd, [switch]$AllowStartIfOnBatteries,
        [switch]$DontStopIfGoingOnBatteries, [TimeSpan]$ExecutionTimeLimit)
    $script:Calls['Settings'] = $PSBoundParameters
    'settings'
}
function New-ScheduledTaskPrincipal {
    [CmdletBinding()] param([string]$UserId, [string]$LogonType, [string]$RunLevel)
    $script:Calls['Principal'] = $PSBoundParameters
    'principal'
}
function Register-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, $Action, $Trigger, $Settings, $Principal, [switch]$Force)
    if ($script:RegisterThrows) { throw 'Access is denied.' }
    $script:Calls['Register'] = $PSBoundParameters
}
function schtasks { throw 'the real scheduler must not be called' }
function Unregister-ScheduledTask { throw 'the real scheduler must not be called' }
function Set-ScheduledTask { throw 'the real scheduler must not be called' }
function Start-ScheduledTask { throw 'the real scheduler must not be called' }
foreach ($name in 'New-ScheduledTaskAction', 'New-ScheduledTaskTrigger', 'New-ScheduledTaskSettingsSet',
                  'New-ScheduledTaskPrincipal', 'Register-ScheduledTask', 'schtasks') {
    if ((Get-Command $name).CommandType -ne 'Function') { throw "$name is not a stand-in" }
}
$env:USERNAME = 'tray-test-user'
"""


def _register(tmp_path: Path, scripts: Path, *, throws: bool = False, port: int = 22051) -> dict[str, str]:
    """Run Register-TrayStartupTask against a fake checkout; return what the stand-ins saw."""
    body = f"""
$script:RegisterThrows = ${str(throws).lower()}
$answer = Register-TrayStartupTask -RepoRoot '{scripts.parent.parent}' -ServerPort {port}
Write-Output ('RESULT:answer=' + (@($answer) -join '+'))
Write-Output ('RESULT:said=' + ($script:Said -join ' | '))
foreach ($call in 'Action', 'Trigger', 'Settings', 'Principal', 'Register') {{
    $shown = @($script:Calls[$call].GetEnumerator() | Sort-Object Key | ForEach-Object {{ '{{0}}={{1}}' -f $_.Key, $_.Value }})
    Write-Output ('RESULT:' + $call + '=' + ($shown -join ';'))
}}
"""
    script = "\n".join([_STUBS, functions("Register-TrayStartupTask"), body])
    return dict(line.split("=", 1) for line in run_powershell(tmp_path, script))


def _checkout(tmp_path: Path, *interpreters: str) -> Path:
    scripts = tmp_path / "checkout" / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    for name in interpreters:
        (scripts / name).write_text("")
    return scripts


@needs_powershell
def test_the_logon_task_is_a_windowless_non_elevated_per_user_task_with_no_time_limit(tmp_path: Path) -> None:
    scripts = _checkout(tmp_path, "python.exe", "pythonw.exe")

    seen = _register(tmp_path, scripts)

    assert seen["answer"] == "True"  # nothing else leaks into the answer
    assert seen["Action"] == (
        f"Argument=-m thomas.tray_agent --port 22051;Execute={scripts / 'pythonw.exe'};WorkingDirectory={scripts.parent.parent}"
    )
    assert seen["Trigger"] == "AtLogon=True;User=tray-test-user"
    assert seen["Principal"] == "LogonType=Interactive;RunLevel=Limited;UserId=tray-test-user"
    assert "ExecutionTimeLimit=00:00:00" in seen["Settings"]  # the default would stop it after 72 hours
    assert seen["Register"].startswith(
        "Action=action;Force=True;Principal=principal;Settings=settings;TaskName=ThomasTrayAgent"
    )


@needs_powershell
def test_without_pythonw_the_task_runs_python_itself(tmp_path: Path) -> None:
    scripts = _checkout(tmp_path, "python.exe")

    seen = _register(tmp_path, scripts)

    assert f"Execute={scripts / 'python.exe'};" in seen["Action"]


@needs_powershell
def test_a_task_windows_refuses_is_reported_with_its_reason_and_answers_false(tmp_path: Path) -> None:
    scripts = _checkout(tmp_path, "python.exe", "pythonw.exe")

    seen = _register(tmp_path, scripts, throws=True)

    assert seen["answer"] == "False"
    assert "Access is denied." in seen["said"]
    assert "No auto-start task was created." in seen["said"]
    assert seen["Register"] == ""  # it threw before recording anything


def test_install_startup_exits_one_when_the_task_was_not_registered() -> None:
    source = script_source()

    block = re.search(r"^if \(\$InstallStartup\) \{\r?\n(.*?)^\}", source, re.S | re.M)
    assert block, "-InstallStartup must be handled at the top level"
    assert re.search(
        r"if \(-not \(Register-TrayStartupTask -RepoRoot \$Root -ServerPort \$Port\)\) \{ exit 1 \}", block.group(1)
    )
    # Nothing is deleted first: a refusal must not leave someone with no task at all.
    assert "schtasks" not in block.group(1)
    assert "schtasks /Delete" not in functions("Register-TrayStartupTask")
    assert block.group(1).index("exit 1") < block.group(1).index("exit 0")
