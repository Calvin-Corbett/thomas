"""The Start Menu "Thomas" shortcut is meant to be hidden and app-like, but left a terminal window open.

launch-thomas.vbs runs run-ui.ps1 hidden, and run-ui.ps1 started the server with
``Start-Process`` and no ``-WindowStyle``, so Windows Terminal opened a window
titled with the path of python.exe for as long as Thomas ran. Closing it, the
natural thing to do with a stray black window, stopped Thomas mid-session. The
server now starts hidden, so the shortcut has to give that Thomas a way to be
stopped: ``/stop`` and ``/restart`` reach run-ui.ps1 as ``-Stop`` and ``-Restart``.
The shortcut also ran the launcher with no log and no message, so a launch that
failed, or one that opened a Thomas it had left running, showed nothing at all. It
now writes a log of its own per launch, keeps the newest five, and says so. The
first test runs the launcher's own server-start function with ``Start-Process``
replaced by a function that records how it was called, so no server starts and no
window opens. The others run a copy of the shortcut script against a stand-in for
run-ui.ps1, in a folder of their own: the real launchers are never run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.launcher_powershell_support import (
    ROOT,
    RUN_REPL,
    RUN_UI,
    needs_windows_powershell,
    ps_path,
    run_functions,
)
from tests.launcher_shortcut_support import launch_logs as _launch_logs
from tests.launcher_shortcut_support import run_shortcut as _run_shortcut
from tests.launcher_shortcut_support import shortcut_copy as _shortcut_copy
from tests.launcher_shortcut_support import stand_in as _stand_in
from tests.launcher_shortcut_support import start_shortcut as _start_shortcut


@needs_windows_powershell
def test_the_server_is_started_with_a_hidden_window(tmp_path: Path) -> None:
    out = run_functions(
        RUN_UI,
        ["Start-DetachedThomasServer"],
        f"""
$Root = {ps_path(tmp_path)}
$VenvPy = 'python.exe'
function Start-Process {{
  param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru, [switch]$NoNewWindow)
  $script:started = 'window=[' + $WindowStyle + '] args=' + ($ArgumentList -join ' ') + ' nonewwindow=' + $NoNewWindow.IsPresent
  return $null
}}
function Wait-ThomasBootHealth {{ param($P, $Attempts, $DelayMs) [pscustomobject]@{{ Ready = $true; Severity = 'healthy' }} }}
$launch = Start-DetachedThomasServer -BindAddress '127.0.0.1' -ServerPort 22000
'started: ' + $script:started
'healthy: ' + $launch.Healthy
""",
        tmp_path,
    )

    assert "started: window=[Hidden] args=-m thomas.server --host 127.0.0.1 --port 22000 nonewwindow=False" in out, out
    assert "healthy: True" in out, out


@needs_windows_powershell
def test_both_launchers_still_parse(tmp_path: Path) -> None:
    """PowerShell's own parser reads both scripts without errors; neither is run."""
    for script in (RUN_UI, RUN_REPL):
        assert "parsed" in run_functions(script, [], "'parsed'", tmp_path), script.name


@pytest.fixture
def cscript_available() -> None:
    if not shutil.which("cscript"):
        pytest.skip("cscript is not available")


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_shortcut_launch_that_fails_shows_the_exit_code_and_where_the_output_is(tmp_path: Path) -> None:
    app = _shortcut_copy(tmp_path, _stand_in(5))
    said = _run_shortcut(app)
    (log,) = _launch_logs(app)

    assert "MSGBOX:Thomas could not start (exit code 5)." in said, said
    assert str(log) in said, said
    assert "stand-in says hello" in log.read_text(encoding="utf-8", errors="replace")


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_shortcut_launch_that_works_shows_nothing(tmp_path: Path) -> None:
    app = _shortcut_copy(tmp_path, _stand_in(0))
    said = _run_shortcut(app)
    (log,) = _launch_logs(app)

    assert "MSGBOX" not in said, said
    assert "stand-in says hello" in log.read_text(encoding="utf-8", errors="replace")


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_second_double_click_during_a_slow_launch_does_not_report_a_failure(tmp_path: Path) -> None:
    """cmd holds its redirect target open for the whole launch, so two launches at once must not share a log."""
    app = _shortcut_copy(tmp_path, _stand_in(0, sleep=6))
    first = _start_shortcut(app)
    time.sleep(2)
    second = _start_shortcut(app)
    said_first, _ = first.communicate(timeout=120)
    said_second, _ = second.communicate(timeout=120)

    assert "MSGBOX" not in said_first and "MSGBOX" not in said_second, (said_first, said_second)
    logs = _launch_logs(app)
    assert len(logs) == 2, logs
    assert all("stand-in says hello" in log.read_text(encoding="utf-8", errors="replace") for log in logs)


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_launch_whose_log_could_not_be_made_does_not_point_at_one(tmp_path: Path) -> None:
    app = _shortcut_copy(tmp_path, _stand_in(5), noticed=False)
    (app / "runtime").write_text("a file where the folder should be", encoding="ascii")
    said = _run_shortcut(app)

    assert "MSGBOX:Thomas could not start (exit code 5)." in said, said
    assert "could not be saved" in said and ".log" not in said, said


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_only_the_newest_launch_logs_are_kept(tmp_path: Path) -> None:
    app = _shortcut_copy(tmp_path, _stand_in(0))
    logs = app / "runtime" / "logs"
    logs.mkdir(parents=True)
    old = [logs / f"launch-20230101-00000{i}-1234.log" for i in range(7)]
    for index, path in enumerate(old):
        path.write_text("an earlier launch", encoding="ascii")
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))
    (logs / "server_stdout.log").write_text("not a launch log", encoding="ascii")
    _run_shortcut(app)

    kept = _launch_logs(app)
    assert len(kept) == 5, kept
    assert [path.name for path in old[3:]] == [path.name for path in kept if path in old], kept
    assert any("stand-in says hello" in path.read_text(encoding="utf-8", errors="replace") for path in kept)
    assert (logs / "server_stdout.log").exists()


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_launch_log_still_open_does_not_stop_the_others_being_pruned(tmp_path: Path) -> None:
    """The server a launch starts inherits that launch's log, so the oldest log is often held open for as long as Thomas runs."""
    app = _shortcut_copy(tmp_path, _stand_in(0))
    logs = app / "runtime" / "logs"
    logs.mkdir(parents=True)
    old = [logs / f"launch-20230101-00000{i}-1234.log" for i in range(7)]
    for index, path in enumerate(old):
        path.write_text("an earlier launch", encoding="ascii")
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))
    with old[0].open("r+b"):  # held open like the log of the launch that started a running server
        _run_shortcut(app)

    kept = _launch_logs(app)
    # The one that cannot be deleted stays; the next-oldest go instead, leaving the newest five (this launch's included).
    assert [path.name for path in kept if path in old] == [old[0].name, *(path.name for path in old[3:])], kept
    assert len(kept) == 6, kept


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
@pytest.mark.parametrize(
    ("argument", "flag", "says"),
    [
        ("/stop", "-Stop", "MSGBOX:Thomas is stopped."),
        ("/STOP", "-Stop", "MSGBOX:Thomas is stopped."),
        ("/restart", "-Restart", ""),
        ("", "", ""),
    ],
)
def test_the_shortcut_hands_stop_and_restart_to_the_launcher(
    tmp_path: Path, argument: str, flag: str, says: str
) -> None:
    """With the server hidden there is no window to close; a Start Menu entry that passes /stop is what stops it."""
    app = _shortcut_copy(tmp_path, _stand_in(0))
    said = _run_shortcut(app, *([argument] if argument else []))
    (log,) = _launch_logs(app)

    assert f"args: {flag}\n" in log.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    assert (says in said) if says else ("MSGBOX" not in said), said


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_stop_during_a_build_says_it_was_not_stopped(tmp_path: Path) -> None:
    app = _shortcut_copy(tmp_path, _stand_in(3))
    said = _run_shortcut(app, "/stop")

    assert "MSGBOX:Thomas is in the middle of a Build run, so it was left running." in said, said
    assert "could not start" not in said, said


@needs_windows_powershell
@pytest.mark.usefixtures("cscript_available")
def test_a_launch_that_opened_another_thomas_than_the_one_launched_says_so(tmp_path: Path) -> None:
    """Exit 4: a Thomas left running (mid-Build, or it would not say) opened instead; the page alone would not tell you."""
    app = _shortcut_copy(tmp_path, _stand_in(4))
    said = _run_shortcut(app)
    (log,) = _launch_logs(app)

    assert "MSGBOX:Thomas opened the copy that was already running." in said, said
    assert f'wscript "{app / "launch-thomas.vbs"}" /restart' in said and str(log) in said, said
    assert "could not start" not in said, said


@needs_windows_powershell
def test_run_ui_cmd_hands_its_arguments_to_the_launcher(tmp_path: Path) -> None:
    """run-ui.cmd dropped them, so -Restart and -Stop could not be given, and the boot doctor's "run-ui.cmd -NoTray" did nothing."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "run-ui.cmd", tmp_path / "run-ui.cmd")
    (tmp_path / "scripts" / "run-ui.ps1").write_text('Write-Host ("args: " + ($args -join " "))\n', encoding="ascii")
    done = subprocess.run(
        ["cmd", "/c", str(tmp_path / "run-ui.cmd"), "-Restart", "-NoTray", "-Port", "22001"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # run-ui.cmd keeps its PowerShell open (-NoExit); end of input closes it
        timeout=120,
        cwd=tmp_path,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    assert "args: -Restart -NoTray -Port 22001" in done.stdout, done.stdout + done.stderr


def test_the_stop_hint_is_the_command_that_works_under_the_default_execution_policy() -> None:
    text = RUN_UI.read_text(encoding="utf-8")

    # The copy's own path, quoted: the launch log is opened from Explorer or Notepad, where a relative path is nowhere.
    assert (
        'to stop it run: powershell -NoProfile -ExecutionPolicy Bypass -File `"$Root\\scripts\\run-ui.ps1`" -Stop -Port $Port"'
        in text
    )
    assert "run scripts\\run-ui.ps1 -" not in text and "run: scripts\\run-ui.ps1" not in text
    assert "-File scripts\\run-ui.ps1" not in text


def test_the_shortcut_tells_a_stranger_what_python_to_install() -> None:
    text = (ROOT / "launch-thomas.vbs").read_text(encoding="utf-8")

    assert "Python 3.10 or newer" in text and "3.13" not in text
