"""The Start Menu server has no window, so the installer has to ship the way to end it.

launch-thomas.vbs starts Thomas hidden, so closing the browser leaves it running and there is no window
to close. Until now the only pointers to an off switch were a message shown once, the launch log and a
command typed by hand, and uninstalling left a server with no window running from a folder that had
been deleted. ThomasSetup.iss now carries Stop Thomas and Restart Thomas entries that hand /stop and
/restart to launch-thomas.vbs, and an [UninstallRun] line that runs run-ui.ps1 -Stop hidden before the
files go. These tests read the installer script, the launcher it calls and the three documents that name
the switch: nothing is installed, compiled or started.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "installer" / "ThomasSetup.iss").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "launch-thomas.vbs").read_text(encoding="utf-8")
RUN_UI = (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")
DOCS = {
    name: (ROOT / name).read_text(encoding="utf-8")
    for name in ("README.md", "ONBOARDING.md", "docs/WINDOWS_INSTALLER_GUIDE.md")
}


def _section(name: str) -> str:
    return ISS.split(f"[{name}]", 1)[1].split("\n[", 1)[0]


def _lines(section: str) -> list[str]:
    """The entries of a section with the #define names filled in, so a test reads what Inno would."""
    names = dict(re.findall(r'^#define (\w+) "([^"]*)"', ISS, re.MULTILINE))
    expanded = re.sub(r"\{#(\w+)\}", lambda m: names.get(m.group(1), m.group(1)), section)
    return [line for line in expanded.splitlines() if re.match(r"(Name|Filename):", line)]


def test_the_start_menu_has_stop_and_restart_entries_that_hand_the_switch_to_the_launcher() -> None:
    entries = {
        m.group(1): line for line in _lines(_section("Icons")) if (m := re.match(r'Name: "\{group\}\\([^"]+)"', line))
    }

    for name, switch in (("Stop Thomas", "/stop"), ("Restart Thomas", "/restart")):
        assert name in entries, f"the Start Menu folder has no {name} entry"
        line = entries[name]
        assert r'Filename: "{sys}\wscript.exe"' in line, line
        assert rf'Parameters: """{{app}}\launch-thomas.vbs"" {switch}"' in line, line
        assert 'WorkingDir: "{app}"' in line and r'IconFilename: "{app}\assets\thomas.ico"' in line, line


def test_the_launcher_those_entries_call_turns_the_switches_into_stop_and_restart() -> None:
    assert re.search(r'LCase\(WScript\.Arguments\(0\)\) = "/stop" Then flag = " -Stop"', LAUNCHER), "launch-thomas.vbs"
    assert re.search(r'LCase\(WScript\.Arguments\(0\)\) = "/restart" Then flag = " -Restart"', LAUNCHER), (
        "launch-thomas.vbs"
    )
    assert "[switch]$Stop" in RUN_UI and "[switch]$Restart" in RUN_UI, "run-ui.ps1 lost a switch the entries rely on"


def test_the_uninstaller_stops_the_server_before_the_folder_it_runs_from_is_deleted() -> None:
    entries = _lines(_section("UninstallRun"))

    assert len(entries) == 1, entries
    line = entries[0]
    assert r'Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"' in line, line
    assert r'-File ""{app}\scripts\run-ui.ps1"" -Stop"' in line, line
    assert "-Restart" not in line, "an uninstall must not start a server"
    assert "-WindowStyle Hidden" in line and "runhidden" in re.search(r"Flags: ([^;]+)", line).group(1).split(), line
    assert "RunOnceId:" in line, "Inno needs an id to run an uninstall entry once"
    assert (ROOT / "scripts" / "run-ui.ps1").is_file()


def test_the_three_documents_say_the_server_has_no_window_and_how_to_end_it() -> None:
    for name, text in DOCS.items():
        flat = " ".join(text.split())
        assert "without a window" in flat, f"{name} does not say the server runs without a window"
        assert "Stop Thomas" in flat and "run-ui.ps1 -Stop" in flat, f"{name} does not say how to stop it"
        assert "Restart Thomas" in flat and "-Restart" in flat, f"{name} does not name the restart switch"
        assert r"runtime\logs" in flat, f"{name} does not say where the launch logs are"
        codes = r"\b0\b[^.]*\b3\b[^.]*\b5\b[^.]*\b6\b"
        assert re.search(codes, flat[flat.index("run-ui.ps1 -Stop") :]), f"{name} does not give the -Stop exit codes"
