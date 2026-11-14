"""Run a copy of launch-thomas.vbs against a stand-in for run-ui.ps1, shared by the shortcut tests.

The real launchers are never run: the copy lives in a folder of its own next to a
stand-in run-ui.ps1 that prints what it was given and exits with a chosen code.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from tests.launcher_powershell_support import ROOT


def shortcut_copy(tmp_path: Path, stand_in: str, *, noticed: bool = True) -> Path:
    """A folder holding launch-thomas.vbs next to a stand-in run-ui.ps1 (the real launcher is never run).

    The copy differs from the real file in one thing: the dialog becomes console
    output, so nothing waits for a click. *noticed* says the once-only note about the
    hidden server was already shown, so a test that is about something else hears nothing.
    """
    app = tmp_path / "app with space"
    (app / "scripts").mkdir(parents=True)
    (app / "scripts" / "run-ui.ps1").write_text(stand_in, encoding="ascii")
    text = (ROOT / "launch-thomas.vbs").read_text(encoding="utf-8")
    probe = re.sub(r'MsgBox message, [^,\r\n]+, "Thomas"', r'WScript.Echo "MSGBOX:" & message', text)
    assert probe != text, "the dialog call was not found"
    (app / "launch-thomas.vbs").write_text(probe, encoding="ascii", newline="\r\n")
    if noticed:
        (app / "runtime").mkdir()
        (app / "runtime" / "background-notice-shown").write_text("", encoding="ascii")
    return app


def start_shortcut(app: Path, *args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [shutil.which("cscript") or "cscript.exe", "//nologo", str(app / "launch-thomas.vbs"), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def run_shortcut(app: Path, *args: str) -> str:
    said, _ = start_shortcut(app, *args).communicate(timeout=120)
    return said


def stand_in(exit_code: int, sleep: int = 0) -> str:
    return (
        'Write-Host "[thomas] stand-in says hello"\n'
        'Write-Host ("args: " + ($args -join " "))\n'
        f"Start-Sleep -Seconds {sleep}\nexit {exit_code}\n"
    )


def launch_logs(app: Path) -> list[Path]:
    return sorted((app / "runtime" / "logs").glob("launch-*.log"))
