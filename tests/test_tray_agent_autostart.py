"""The tray's "Auto-start with Windows" item saves only what Windows really did.

`schtasks` is always faked; nothing here registers, queries or removes a task.
"""

from __future__ import annotations

import re
import subprocess
import sys
import types
import xml.etree.ElementTree as ET  # parses the task file this module wrote itself
from pathlib import Path

import pytest

from thomas.tray_agent import agent as tray
from thomas.tray_agent import autostart

_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
_MISSING = "ERROR: The system cannot find the file specified."


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "tray_state.json")
    monkeypatch.setattr(tray, "_LOG_FILE", tmp_path / "tray_agent.log")
    monkeypatch.setattr(tray, "_SERVER_LOG_FILE", tmp_path / "server.log")
    return tmp_path


def _fake_schtasks(monkeypatch, returncode: int = 0, stderr: str = "ERROR: nope") -> list[dict]:
    """Stand in for schtasks. Each call records its command, keyword arguments and,
    for /Create /XML, the task file as it was on disk while schtasks would read it."""
    seen: list[dict] = []

    def fake_run(cmd, **kwargs):
        call = {"cmd": list(cmd), "kwargs": kwargs, "xml": None, "xml_path": None}
        if "/XML" in cmd:
            call["xml_path"] = Path(cmd[cmd.index("/XML") + 1])
            call["xml"] = ET.fromstring(call["xml_path"].read_bytes())
        seen.append(call)
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(tray.subprocess, "run", fake_run)
    return seen


# --- The task Windows is asked for ---------------------------------------------


def test_auto_start_registers_a_per_user_logon_task(state_dir, monkeypatch) -> None:
    monkeypatch.setenv("USERDOMAIN", "TESTBOX")
    monkeypatch.setenv("USERNAME", "a&b")  # must be escaped, not break the file
    seen = _fake_schtasks(monkeypatch)

    assert tray.enable_auto_start(port=22050) is True

    cmd, task = seen[0]["cmd"], seen[0]["xml"]
    # `/SC ONLOGON` names no user in its trigger; a task file whose trigger names this user does.
    assert cmd[1] == "/Create"
    assert "/SC" not in cmd and "/RL" not in cmd
    assert task.find("t:Triggers/t:LogonTrigger/t:UserId", _NS).text == "TESTBOX\\a&b"
    assert task.find("t:Principals/t:Principal/t:UserId", _NS).text == "TESTBOX\\a&b"
    assert task.find("t:Principals/t:Principal/t:RunLevel", _NS).text == "LeastPrivilege"
    assert task.find("t:Principals/t:Principal/t:LogonType", _NS).text == "InteractiveToken"
    # The default limit stops a task after 72 hours; the tray is meant to run all day.
    assert task.find("t:Settings/t:ExecutionTimeLimit", _NS).text == "PT0S"


def test_the_logon_task_runs_the_command_line_run_ui_recognises(state_dir, monkeypatch) -> None:
    seen = _fake_schtasks(monkeypatch)

    tray.enable_auto_start(port=22050)

    action = seen[0]["xml"].find("t:Actions/t:Exec", _NS)
    arguments = action.find("t:Arguments", _NS).text
    assert arguments == "-m thomas.tray_agent --port 22050"
    assert action.find("t:WorkingDirectory", _NS).text == str(tray._get_repo_root())
    # run-ui.ps1 stops a tray only when its command line matches this; a task that ran
    # __main__.py by path would be invisible to it.
    launcher = (tray._get_repo_root() / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")
    assert r"-m\s+thomas\.tray_agent\b" in launcher
    assert re.search(r"-m\s+thomas\.tray_agent\b", arguments)


def test_the_task_file_is_removed_whether_or_not_windows_accepts_it(state_dir, monkeypatch) -> None:
    for returncode in (0, 1):
        seen = _fake_schtasks(monkeypatch, returncode=returncode)

        tray.enable_auto_start()

        assert not seen[0]["xml_path"].exists()


def test_auto_start_runs_the_windowless_interpreter_when_there_is_one(state_dir, tmp_path, monkeypatch) -> None:
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(tray, "_get_exe_path", lambda: str(tmp_path / "python.exe"))
    seen = _fake_schtasks(monkeypatch)

    tray.enable_auto_start()

    assert seen[0]["xml"].find("t:Actions/t:Exec/t:Command", _NS).text == str(tmp_path / "pythonw.exe")


def test_auto_start_runs_python_itself_when_no_pythonw_sits_beside_it(state_dir, tmp_path, monkeypatch) -> None:
    (tmp_path / "python.exe").write_text("")  # a venv without pythonw.exe: the task must not name a missing file
    monkeypatch.setattr(tray, "_get_exe_path", lambda: str(tmp_path / "python.exe"))
    seen = _fake_schtasks(monkeypatch)

    tray.enable_auto_start()

    assert seen[0]["xml"].find("t:Actions/t:Exec/t:Command", _NS).text == str(tmp_path / "python.exe")


def test_a_refused_task_is_not_reported_as_enabled(state_dir, monkeypatch) -> None:
    _fake_schtasks(monkeypatch, returncode=1)

    assert tray.enable_auto_start() is False


def test_every_schtasks_call_opens_no_console_window(state_dir, monkeypatch) -> None:
    """Under pythonw.exe a bare subprocess.run opens a terminal window, once per call."""
    seen = _fake_schtasks(monkeypatch)

    tray.is_auto_start_enabled()  # the menu runs this each time it is built
    tray.enable_auto_start()
    tray.disable_auto_start()

    expected = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    assert [call["cmd"][1] for call in seen] == ["/Query", "/Create", "/Delete"]
    for call in seen:
        assert call["kwargs"]["creationflags"] == expected, call["cmd"]
        # schtasks answers in the OEM code page; a stray byte must not raise out of the menu.
        assert call["kwargs"]["errors"] == "replace"


# --- What the menu tick reads, and what removing the task answers --------------


@pytest.mark.parametrize(("returncode", "enabled"), [(0, True), (1, False)])
def test_the_menu_tick_follows_whether_schtasks_finds_the_task(state_dir, monkeypatch, returncode, enabled) -> None:
    _fake_schtasks(monkeypatch, returncode=returncode)

    assert tray.is_auto_start_enabled() is enabled


@pytest.mark.parametrize("error", [OSError("no schtasks"), subprocess.TimeoutExpired("schtasks", 10)])
def test_a_query_that_cannot_run_reads_as_not_enabled(monkeypatch, error) -> None:
    def fail(cmd, **kwargs):
        raise error

    monkeypatch.setattr(tray.subprocess, "run", fail)

    assert autostart.is_enabled() is False


@pytest.mark.parametrize(
    ("returncode", "stderr", "removed"),
    [
        (0, "", True),
        (1, _MISSING, True),  # nothing to remove: it is off, which is what was asked
        (1, "ERROR: Access is denied.", False),
    ],
)
def test_removing_the_task_answers_true_only_when_it_is_gone(
    state_dir, monkeypatch, returncode, stderr, removed
) -> None:
    _fake_schtasks(monkeypatch, returncode=returncode, stderr=stderr)

    assert tray.disable_auto_start() is removed


def test_a_removal_that_cannot_run_answers_false(monkeypatch) -> None:
    def fail(cmd, **kwargs):
        raise OSError("no schtasks")

    monkeypatch.setattr(tray.subprocess, "run", fail)

    assert autostart.disable() is False


# --- Toggling from the menu ----------------------------------------------------


def _toggle_agent(state_dir, monkeypatch, *, task_present: bool, windows_accepts: bool):
    """An agent whose Windows side is faked; returns it with the calls and notices it made."""
    agent = tray.ThomasTrayAgent(port=22051)
    agent.state.auto_start_enabled = task_present
    calls: list[str] = []
    told: list[str] = []
    monkeypatch.setattr(agent, "_notify", told.append)
    monkeypatch.setattr(tray, "is_auto_start_enabled", lambda: task_present)
    monkeypatch.setattr(tray, "enable_auto_start", lambda port=0: calls.append("enable") or windows_accepts)
    monkeypatch.setattr(tray, "disable_auto_start", lambda: calls.append("disable") or windows_accepts)
    return agent, calls, told


def test_toggling_auto_start_does_not_save_success_when_windows_refuses(state_dir, monkeypatch) -> None:
    agent, calls, told = _toggle_agent(state_dir, monkeypatch, task_present=False, windows_accepts=False)

    assert agent.toggle_auto_start() is False

    assert calls == ["enable"]
    assert agent.state.auto_start_enabled is False
    assert not (state_dir / "tray_state.json").exists()
    assert told and "turn auto-start on" in told[0]


def test_toggling_auto_start_saves_success_when_windows_accepts(state_dir, monkeypatch) -> None:
    agent, calls, told = _toggle_agent(state_dir, monkeypatch, task_present=False, windows_accepts=True)

    assert agent.toggle_auto_start() is True

    assert calls == ["enable"]
    assert tray.TrayState.load().auto_start_enabled is True
    assert told == []


def test_toggling_auto_start_off_removes_the_task_and_saves_off(state_dir, monkeypatch) -> None:
    agent, calls, told = _toggle_agent(state_dir, monkeypatch, task_present=True, windows_accepts=True)

    assert agent.toggle_auto_start() is True

    assert calls == ["disable"]  # a task that exists is removed, never registered again
    assert agent.state.auto_start_enabled is False
    assert tray.TrayState.load().auto_start_enabled is False
    assert told == []


def test_a_refused_removal_saves_nothing_and_says_it_could_not_turn_it_off(state_dir, monkeypatch) -> None:
    agent, calls, told = _toggle_agent(state_dir, monkeypatch, task_present=True, windows_accepts=False)

    assert agent.toggle_auto_start() is False

    assert calls == ["disable"]
    assert agent.state.auto_start_enabled is True  # the task is still there, so the flag must stay
    assert not (state_dir / "tray_state.json").exists()
    assert told and "turn auto-start off" in told[0]


def test_auto_start_is_off_until_a_task_exists() -> None:
    assert tray.TrayState().auto_start_enabled is False
    assert tray.TrayState.from_dict({}).auto_start_enabled is False
