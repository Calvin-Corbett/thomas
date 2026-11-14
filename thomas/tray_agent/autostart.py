"""Windows Task Scheduler side of "Auto-start with Windows" for the tray agent.

Pure helpers: the caller says which interpreter and checkout the task should run.
"""

from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

TASK_NAME = "ThomasTrayAgent"


def _run_schtasks(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run schtasks without a console window.

    The logon task starts pythonw.exe, which has no console of its own, so a bare
    subprocess.run from there opens a terminal window on every call; the menu
    queries the task each time it is built.
    """
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        errors="replace",  # schtasks answers in the OEM code page; a stray byte must not raise
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def task_xml(port: int, exe: str, repo_root: str) -> str:
    """Task Scheduler definition: at this user's logon, not elevated, in this checkout.

    `schtasks /Create /SC ONLOGON` names no user in the trigger, and has no flag
    for the time limit or the working directory. A task file can set all three, and
    its trigger names this user, the same kind start-tray-agent.ps1
    -InstallStartup registers. Whether the no-user form needs administrator rights
    is expected but was never checked (nothing here registered a task). The `-m
    thomas.tray_agent --port N` command line is the one run-ui.ps1 looks for when
    it has to stop a tray.
    """
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME") or getpass.getuser()
    user = escape(f"{domain}\\{name}" if domain else name)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>-m thomas.tray_agent --port {int(port)}</Arguments>
      <WorkingDirectory>{escape(repo_root)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def is_enabled() -> bool:
    """Check if auto-start is configured in Windows Task Scheduler."""
    try:
        return _run_schtasks(["/Query", "/TN", TASK_NAME], timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enable(port: int, exe: str, repo_root: str) -> bool:
    """Enable auto-start at Windows logon via Task Scheduler.

    True only when schtasks accepted the task; the caller must not record
    "enabled" from anything else.
    """
    definition = ""
    try:
        # A task file, not /SC ONLOGON on the command line: see task_xml.
        # ExecutionTimeLimit PT0S matters too; the default stops a task after 72 hours.
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as handle:
            definition = handle.name
            handle.write(task_xml(port, exe, repo_root))
        result = _run_schtasks(["/Create", "/TN", TASK_NAME, "/XML", definition, "/F"], timeout=30)
        if result.returncode == 0:
            log.info("Auto-start enabled via Task Scheduler")
            return True
        log.error("Failed to enable auto-start: %s", (result.stderr or result.stdout).strip())
        return False
    except (OSError, subprocess.SubprocessError) as e:
        log.error("Failed to enable auto-start: %s", e)
        return False
    finally:
        if definition:
            try:
                os.unlink(definition)
            except OSError:
                pass  # a temp file we could not remove is harmless


def disable() -> bool:
    """Disable auto-start."""
    try:
        result = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"], timeout=30)
        if result.returncode == 0 or "The system cannot find the file specified" in result.stderr:
            log.info("Auto-start disabled")
            return True
        log.error("Failed to disable auto-start: %s", result.stderr)
        return False
    except (OSError, subprocess.SubprocessError) as e:
        log.error("Failed to disable auto-start: %s", e)
        return False
