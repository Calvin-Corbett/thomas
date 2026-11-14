"""The server now starts without a window, so nothing on screen says it is there or ends it.

Closing the browser does not stop it, and the console window that used to be the off
switch is gone. The Start Menu shortcut (launch-thomas.vbs) says so once, after the
first launch that worked, with the command that stops it: ``/stop`` reaches run-ui.ps1
as ``-Stop``. runtime\\ remembers that it was said. These tests run a copy of the
shortcut against a stand-in for run-ui.ps1, in a folder of their own.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.launcher_powershell_support import ROOT, needs_windows_powershell
from tests.launcher_shortcut_support import launch_logs, run_shortcut, shortcut_copy, stand_in

pytestmark = [needs_windows_powershell, pytest.mark.usefixtures("cscript_available")]

NOTE = "MSGBOX:Thomas started from this shortcut runs in the background, with no window of its own"


@pytest.fixture
def cscript_available() -> None:
    if not shutil.which("cscript"):
        pytest.skip("cscript is not available")


def _marker(app: Path) -> Path:
    return app / "runtime" / "background-notice-shown"


def test_the_first_launch_that_works_says_the_server_has_no_window_and_how_to_stop_it(tmp_path: Path) -> None:
    app = shortcut_copy(tmp_path, stand_in(0), noticed=False)
    said = run_shortcut(app)

    assert NOTE in said, said
    assert "closing the browser does not stop it" in said, said
    # The command is this copy's own script with /stop, which reaches run-ui.ps1 as -Stop.
    assert f'wscript "{app / "launch-thomas.vbs"}" /stop' in said, said
    assert _marker(app).exists()


def test_it_is_said_once(tmp_path: Path) -> None:
    app = shortcut_copy(tmp_path, stand_in(0), noticed=False)
    first = run_shortcut(app)
    second = run_shortcut(app)
    third = run_shortcut(app)

    assert NOTE in first and first.count("MSGBOX") == 1, first
    assert "MSGBOX" not in second and "MSGBOX" not in third, (second, third)
    assert len(launch_logs(app)) == 3


def test_a_launch_that_failed_does_not_use_up_the_note(tmp_path: Path) -> None:
    app = shortcut_copy(tmp_path, stand_in(5), noticed=False)
    failed = run_shortcut(app)

    assert "MSGBOX:Thomas could not start (exit code 5)." in failed and NOTE not in failed, failed
    assert not _marker(app).exists()
    (app / "scripts" / "run-ui.ps1").write_text(stand_in(0), encoding="ascii")
    assert NOTE in run_shortcut(app)


@pytest.mark.parametrize(("argument", "says"), [("/stop", "MSGBOX:Thomas is stopped."), ("/restart", "")])
def test_stopping_or_restarting_on_purpose_does_not_explain_what_you_just_did(
    tmp_path: Path, argument: str, says: str
) -> None:
    app = shortcut_copy(tmp_path, stand_in(0), noticed=False)
    said = run_shortcut(app, argument)

    assert NOTE not in said, said
    assert (says in said) if says else ("MSGBOX" not in said), said
    assert not _marker(app).exists()
    # The note is still to come on the next plain launch.
    assert NOTE in run_shortcut(app)


def test_a_launch_that_left_another_thomas_running_keeps_its_own_message_and_the_note_for_later(tmp_path: Path) -> None:
    app = shortcut_copy(tmp_path, stand_in(4), noticed=False)
    said = run_shortcut(app)

    assert "MSGBOX:Thomas opened the copy that was already running." in said and NOTE not in said, said
    assert not _marker(app).exists()


def test_a_degraded_thomas_is_said_to_be_degraded_with_the_way_to_restart_it(tmp_path: Path) -> None:
    """Exit 7: the running copy was opened, but it reports degraded; the note about the hidden server waits."""
    app = shortcut_copy(tmp_path, stand_in(7), noticed=False)
    said = run_shortcut(app)

    assert "MSGBOX:Thomas opened the copy that was already running, but it reports that it is degraded" in said, said
    assert f'wscript "{app / "launch-thomas.vbs"}" /restart' in said, said
    assert "What it reported is saved in:" in said and NOTE not in said, said
    assert not _marker(app).exists()


def test_a_stop_that_found_nothing_does_not_say_thomas_is_stopped(tmp_path: Path) -> None:
    """run-ui.ps1 -Stop exits 5 when it found no Thomas to end: on the port it asked about, or on the recorded one."""
    said = run_shortcut(shortcut_copy(tmp_path, stand_in(5)), "/stop")

    assert "MSGBOX:No Thomas was found to stop." in said, said
    assert "is stopped" not in said, said
    # The launch log says which ports were looked at, so the box points at it.
    assert "What it reported is saved in:" in said, said


@pytest.mark.parametrize("code", [6, 1])
def test_a_stop_that_could_not_end_a_thomas_says_so(tmp_path: Path, code: int) -> None:
    """Exit 6 is a Thomas still there after the stop; any other code is the launcher failing, which is not 'started' either."""
    said = run_shortcut(shortcut_copy(tmp_path, stand_in(code)), "/stop")

    assert f"MSGBOX:Thomas could not be stopped (exit code {code})." in said, said
    assert "is stopped" not in said and "could not start" not in said, said


def test_a_stop_during_a_build_keeps_its_own_message(tmp_path: Path) -> None:
    said = run_shortcut(shortcut_copy(tmp_path, stand_in(3)), "/stop")

    assert "MSGBOX:Thomas is in the middle of a Build run, so it was left running." in said, said


def test_every_dialog_is_shown_in_the_foreground() -> None:
    """A box from this background script is otherwise often put behind the window that just took focus.

    A test cannot see window order, so this reads the source: there is one MsgBox call, every
    dialog goes through it, and it adds MB_SETFOREGROUND (65536) to the icon.
    """
    text = (ROOT / "launch-thomas.vbs").read_text(encoding="utf-8")

    assert len(re.findall(r"\bMsgBox\b", text)) == 1
    call = re.search(r'MsgBox message, icon \+ (\w+), "Thomas"', text)
    assert call, "the dialog no longer adds a flag to the icon"
    flag = re.search(rf"^Const {call.group(1)} = (\d+)", text, re.MULTILINE)
    assert flag and int(flag.group(1)) & 0x10000, "the dialog is not raised with MB_SETFOREGROUND"


def test_with_nowhere_to_remember_it_nothing_is_said_rather_than_said_every_time(tmp_path: Path) -> None:
    app = shortcut_copy(tmp_path, stand_in(0), noticed=False)
    (app / "runtime").write_text("a file where the folder should be", encoding="ascii")

    assert "MSGBOX" not in run_shortcut(app)
    assert "MSGBOX" not in run_shortcut(app)
