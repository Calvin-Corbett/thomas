"""Runs the generated Thomas.vbs launcher with every side effect replaced by a fake that writes it down.

The launcher runs under Windows Script Host with its shell, file system, process list and
message boxes replaced by in-script fakes, so nothing is launched, installed or shown. The one
real thing left is the health probe: it asks a scratch port on 127.0.0.1 that each scenario
controls (answering, refusing the connection, or accepting and never replying).

A scenario says which files exist, what the shell refuses to run, what the process list holds
(each as a command line and how many minutes ago it started), how each message box is answered,
and what the scratch port does. What comes back is the list of things the launcher did, in order.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from scripts import thomas_app

CSCRIPT = shutil.which("cscript") if sys.platform.startswith("win") else None

PREAMBLE = """Option Explicit
Dim gFail, gExists, gAnswers, gProcs
gFail = "__FAIL__"
gExists = "__EXISTS__"
gAnswers = "__ANSWERS__"
Class FakeProc
    Public CommandLine
    Public CreationDate
End Class
Function MakeProc(c, d)
    Dim p
    Set p = New FakeProc
    p.CommandLine = c
    p.CreationDate = d
    Set MakeProc = p
End Function
gProcs = Array(__PROCS__)
Class FakeWmi
    Public Function ExecQuery(q)
        If InStr(gFail, "wmi") > 0 Then Err.Raise 5, "FakeWmi", "the process list cannot be read"
        ExecQuery = gProcs
    End Function
End Class
Class FakeShell
    Public Property Let CurrentDirectory(v)
        WScript.Echo "CWD|" & v
    End Property
    Public Function ExpandEnvironmentStrings(s)
        ExpandEnvironmentStrings = "C:\\fake\\Local"
    End Function
    Public Function Run(cmd, style, wait)
        WScript.Echo "RUN|" & style & "|" & cmd
        If InStr(gFail, "electron") > 0 And InStr(cmd, "electron.exe") > 0 Then Err.Raise 5, "FakeShell", "blocked"
        If InStr(gFail, "msedge") > 0 And Left(cmd, 6) = "msedge" Then Err.Raise 5, "FakeShell", "no msedge"
        If InStr(gFail, "chrome") > 0 And Left(cmd, 6) = "chrome" Then Err.Raise 5, "FakeShell", "no chrome"
        Run = 0
    End Function
    Public Function Popup(msg, secs, title, flags)
        WScript.Echo "POPUP|" & Replace(msg, vbCrLf, " ")
        Popup = 0
    End Function
End Class
Class FakeFso
    Public Function FileExists(p)
        FileExists = (InStr(gExists, "|" & LCase(Mid(p, 9)) & "|") > 0)
    End Function
    Public Function FolderExists(p)
        FolderExists = True
    End Function
    Public Function GetParentFolderName(p)
        GetParentFolderName = "C:\\fake"
    End Function
    Public Sub CreateFolder(p)
    End Sub
End Class
Function FakeMsgBox(a, b, c)
    Dim k, at
    k = "?"
    If InStr(a, "desktop shell") > 0 Then k = "shell"
    If InStr(a, "already be starting") > 0 Then k = "again"
    If InStr(a, "not fully set up") > 0 Then k = "setup"
    WScript.Echo "MSGBOX|" & k & "|" & b
    WScript.Echo "PROMPT|" & k & "|" & Replace(a, vbCrLf, "<CRLF>")
    FakeMsgBox = 7
    at = InStr(gAnswers, "|" & k & "=")
    If at > 0 Then FakeMsgBox = CInt(Mid(gAnswers, at + Len(k) + 2, 1))
End Function
"""

ELECTRON = "desktop\\node_modules\\electron\\dist\\electron.exe"
DESKTOP_PS1 = "scripts\\run-desktop.ps1"
LAUNCH = "launch-thomas.vbs"
RUN_UI = "scripts\\run-ui.ps1"
VENV = ".venv\\scripts\\python.exe"
VENV_CFG = ".venv\\pyvenv.cfg"
SETUP_DONE = "runtime\\setup\\last_setup.txt"
EVERYTHING = [ELECTRON, DESKTOP_PS1, LAUNCH, RUN_UI, VENV, VENV_CFG, SETUP_DONE]
SET_UP = [LAUNCH, RUN_UI, VENV, VENV_CFG, SETUP_DONE]
RUNNING = 'powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\fake\\scripts\\run-ui.ps1"'


def began(minutes_ago: float) -> str:
    """A WMI start time (local time, yyyymmddHHMMSS.ffffff+UUU) this many minutes ago."""
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y%m%d%H%M%S") + ".000000+000"


def _vbs_text(value: str) -> str:
    return value.replace('"', '""')


def _scripted(text: str, scenario: dict, port: int) -> str:
    head, rest = text.split("\n", 1)
    assert head == "Option Explicit"
    body = (
        rest.replace('CreateObject("WScript.Shell")', "New FakeShell")
        .replace('CreateObject("Scripting.FileSystemObject")', "New FakeFso")
        .replace('GetObject("winmgmts:root\\cimv2")', "New FakeWmi")
        .replace("Set procs = wmi.ExecQuery(", "procs = wmi.ExecQuery(")  # the fake hands back an array
        .replace("WScript.ScriptFullName", '"C:\\fake\\Thomas.vbs"')
        .replace("MsgBox(", "FakeMsgBox(")
    )
    body = re.sub(r"127\.0\.0\.1:\d+", f"127.0.0.1:{port}", body)
    # A number is dated here, as the launcher runs: dated when the test file is imported, it aged all through a long run.
    dates = [(cmd, began(age) if isinstance(age, (int, float)) else age) for cmd, age in scenario.get("procs", [])]
    made = ", ".join(f'MakeProc("{_vbs_text(cmd)}", "{date}")' for cmd, date in dates)
    answers = "|" + "|".join(f"{k}={v}" for k, v in scenario.get("answers", {}).items()) + "|"
    out = (
        PREAMBLE.replace("__FAIL__", scenario.get("fail", ""))
        .replace("__EXISTS__", "|" + "|".join(scenario["exists"]) + "|")
        .replace("__ANSWERS__", answers)
        .replace("__PROCS__", made)
        + body
        + '\nWScript.Echo "END"\n'
    )
    # Safety: nothing real may be left to act on the machine except the loopback health probe.
    assert all("MSXML2" in c for c in re.findall(r"CreateObject\(([^)]*)\)", out)), "a real object survives"
    assert "GetObject" not in out and "WScript.Shell" not in out.replace("FakeShell", "")
    return out


class _Answers(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def _server(state: str) -> tuple[int, object]:
    """A scratch port in one state, and what closes it: answering, refusing, or never replying."""
    if state == "up":
        srv = HTTPServer(("127.0.0.1", 0), _Answers)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv.server_port, srv
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    if state == "busy":
        sock.listen(5)  # accepts the connection into its queue and never replies
        return port, sock
    sock.close()  # refused: nothing listens here any more
    return port, None


def _kind(style: str, cmd: str) -> str:
    """A Run the fake shell was asked to make, named by what it launches."""
    if "run-ui.ps1" in cmd:
        return f"run-ui(style={style}{', stays open' if '-NoExit' in cmd else ''})"
    if "launch-thomas.vbs" in cmd:
        return f"launch-thomas(style={style})"
    contains = {"electron.exe": "electron", "run-desktop.ps1": "install-shell", "schtasks": "schtasks"}
    starts = {"msedge": "msedge", "chrome": "chrome", "http": "url"}
    found = [v for k, v in contains.items() if k in cmd] + [v for k, v in starts.items() if cmd.startswith(k)]
    return found[0] if found else "?" + cmd


def _popup(text: str) -> str:
    note = "desktop shell could not be started" in text
    if text.startswith("Starting Thomas"):
        return "popup:starting" + ("+shell-note" if note else "")
    if text.startswith("Nothing was installed"):
        return "popup:declined"
    return "popup:shell-note" if note else "popup:?" + text


def _kinds(stdout: str) -> list[str]:
    out: list[str] = []
    for line in (ln.strip() for ln in stdout.splitlines() if ln.strip()):
        if line.startswith("RUN|"):
            _, style, cmd = line.split("|", 2)
            out.append(_kind(style, cmd))
        elif line.startswith("POPUP|"):
            out.append(_popup(line[len("POPUP|") :]))
        elif line.startswith("MSGBOX|"):
            _, name, flags = line.split("|")
            default_no = int(flags) & 768 == 256 and int(flags) & 7 == 4  # Yes/No, second button the default
            out.append(f"msgbox:{name}" + ("(default No)" if default_no else ""))
        elif line == "END":
            out.append(line)
    return out


def prompts(stdout: str) -> dict[str, str]:
    """The text of each message box the launcher showed, by the name the fake gave it."""
    shown = (line.split("|", 2) for line in stdout.splitlines() if line.startswith("PROMPT|"))
    return {name: text.replace("<CRLF>", "\r\n") for _, name, text in shown}


def run_scenario(tmp_path: Path, name: str, scenario: dict) -> list[str]:
    kinds, _stdout = run_scenario_with_output(tmp_path, name, scenario)
    return kinds


def run_scenario_with_output(tmp_path: Path, name: str, scenario: dict) -> tuple[list[str], str]:
    """What the launcher did, in order, and everything the fake host printed while it did it."""
    text = thomas_app.render_launcher(scenario.get("port", thomas_app.DEFAULT_PORT), caged=scenario.get("caged", False))
    port, closer = _server(scenario["server"])
    script = tmp_path / f"{name}.vbs"
    script.write_bytes(_scripted(text, scenario, port).replace("\n", "\r\n").encode("ascii"))
    try:
        done = subprocess.run(  # noqa: S603 - Windows Script Host on a scratch file of fakes
            [CSCRIPT, "//nologo", "//T:40", str(script)], capture_output=True, check=False, text=True, timeout=90
        )
    finally:
        if isinstance(closer, HTTPServer):
            closer.shutdown()
            closer.server_close()
        elif closer is not None:
            closer.close()
    assert not done.stderr.strip(), done.stderr
    return [*_kinds(done.stdout), f"exit {done.returncode}"], done.stdout


def cscript(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Windows Script Host on a scratch file (never on a launcher: the callers make it inert)."""
    return subprocess.run(  # noqa: S603 - Windows Script Host on a scratch file
        [CSCRIPT, "//nologo", "//T:30", str(script), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )


def write_vbs(path: Path, body: str) -> Path:
    path.write_bytes(("Option Explicit\n" + body).replace("\n", "\r\n").encode("ascii"))
    return path


def wrong_scenarios(tmp_path: Path, scenarios: dict[str, tuple[dict, list[str]]]) -> list[str]:
    """Run every scenario (a few at a time) and describe each one that did something else."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            name: pool.submit(run_scenario, tmp_path, f"scenario_{i}", scenario)
            for i, (name, (scenario, _)) in enumerate(scenarios.items())
        }
        got = {name: future.result() for name, future in futures.items()}
    return [
        f"{name}\n    expected {want}\n    got      {got[name]}"
        for name, (_, want) in scenarios.items()
        if got[name] != want
    ]
