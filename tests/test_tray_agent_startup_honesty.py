"""The tray agent reports what really happened: headless mode, status, bad settings.

The tray itself is always faked; nothing here opens an icon. Auto-start is in
test_tray_agent_autostart.py.
"""

from __future__ import annotations

import io
import logging
import sys
import types
from pathlib import Path

import pytest

from thomas.tray_agent import agent as tray


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "tray_state.json")
    monkeypatch.setattr(tray, "_LOG_FILE", tmp_path / "tray_agent.log")
    monkeypatch.setattr(tray, "_SERVER_LOG_FILE", tmp_path / "server.log")
    return tmp_path


# --- Headless mode says so -----------------------------------------------------


def _run_once(agent: tray.ThomasTrayAgent, monkeypatch) -> None:
    class Quiet:
        def start(self) -> bool:
            return True

        def stop(self) -> None:
            pass

    agent.server = Quiet()
    monkeypatch.setattr(tray, "HEALTHCHECK_INTERVAL_S", 0.01)
    monkeypatch.setattr(agent, "_setup_logging", lambda: None)
    agent._stop_event.set()  # the headless loop returns as soon as it starts
    agent.run()


def test_a_missing_pystray_is_named_when_the_agent_starts(state_dir, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "pystray", None)  # makes `import pystray` raise ImportError
    agent = tray.ThomasTrayAgent(port=22053)

    _run_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "headless" in out
    assert "no tray icon" in out
    assert "pystray could not be loaded" in out
    assert "pip install pystray pillow win10toast" in out
    assert "http://127.0.0.1:22053/" in out


def test_no_tray_flag_says_it_was_asked_for_not_that_pystray_is_missing(state_dir, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "pystray", None)
    agent = tray.ThomasTrayAgent(port=22054)
    agent.force_headless()

    _run_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "--no-tray" in out
    assert "pystray" not in out


@pytest.mark.parametrize(
    ("toast_installed", "says_no_notifications"),
    [(False, True), (True, False)],
)
def test_headless_claims_no_notifications_only_when_win10toast_is_missing(
    state_dir, monkeypatch, capsys, toast_installed, says_no_notifications
) -> None:
    """Toasts come from win10toast, not pystray, so a missing tray does not silence them."""
    monkeypatch.setitem(sys.modules, "pystray", None)
    monkeypatch.setattr(tray, "_module_available", lambda name: toast_installed)
    agent = tray.ThomasTrayAgent(port=22056)

    _run_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "no tray icon" in out
    assert ("no notifications" in out) is says_no_notifications


def test_the_pip_hint_names_python_not_pythonw_and_quotes_a_path_with_spaces(monkeypatch) -> None:
    monkeypatch.setattr(tray, "_get_exe_path", lambda: r"C:\Program Files\Thomas\.venv\Scripts\pythonw.exe")
    assert tray._pip_command() == r'"C:\Program Files\Thomas\.venv\Scripts\python.exe" -m pip'

    monkeypatch.setattr(tray, "_get_exe_path", lambda: r"C:\T\.venv\Scripts\python.exe")
    assert tray._pip_command() == r"C:\T\.venv\Scripts\python.exe -m pip"


def test_the_console_hears_a_message_once(state_dir, monkeypatch, capsys) -> None:
    agent = tray.ThomasTrayAgent(port=22057)

    agent._console_log = True  # the log line already reaches the console
    agent._say("only in the log")
    assert capsys.readouterr().out == ""

    agent._console_log = False  # pythonw, or a launcher that captured nothing
    agent._say("printed too")
    assert "[thomas] printed too" in capsys.readouterr().out


def test_a_console_handler_is_told_apart_from_a_file_or_a_missing_stderr(tmp_path) -> None:
    root = logging.Logger("scratch")
    assert tray._console_log_attached(root) is False

    root.addHandler(logging.FileHandler(tmp_path / "tray.log", encoding="utf-8"))
    assert tray._console_log_attached(root) is False  # a file is not a console

    no_stderr = logging.StreamHandler(io.StringIO())
    no_stderr.stream = None  # what pythonw.exe gives it
    root.addHandler(no_stderr)
    assert tray._console_log_attached(root) is False

    root.addHandler(logging.StreamHandler(io.StringIO()))
    assert tray._console_log_attached(root) is True
    for handler in list(root.handlers):
        handler.close()


def _console_found_by_setup_logging(agent: tray.ThomasTrayAgent, monkeypatch) -> bool:
    """Run the real _setup_logging on a bare root logger and return what the agent concluded."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])  # basicConfig adds its console handler only to a bare root
    monkeypatch.setattr(root, "level", root.level)
    try:
        agent._setup_logging()
        return agent._console_log
    finally:
        for handler in list(root.handlers):
            handler.close()


def test_the_agent_learns_from_its_real_logging_setup_whether_a_console_hears_the_log(state_dir, monkeypatch) -> None:
    # A console is attached: the log line reaches it, so _say must not print the message again.
    assert _console_found_by_setup_logging(tray.ThomasTrayAgent(port=22061), monkeypatch) is True

    # pythonw.exe has no stderr: the handler logging adds has nothing to write to, so _say prints.
    monkeypatch.setattr(sys, "stderr", None)
    assert _console_found_by_setup_logging(tray.ThomasTrayAgent(port=22062), monkeypatch) is False


# --- Status shown by the icon --------------------------------------------------


@pytest.mark.parametrize(
    ("running", "healthy", "status"),
    [(True, True, "active"), (True, False, "working"), (False, False, "stopped")],
)
def test_icon_status_follows_health_not_just_the_process(state_dir, running, healthy, status) -> None:
    agent = tray.ThomasTrayAgent(port=22055)
    agent.server = types.SimpleNamespace(is_running=lambda: running, is_healthy=lambda: healthy)

    assert agent._tray_status() == status


def test_each_icon_status_is_drawn_in_its_own_colour() -> None:
    pytest.importorskip("PIL")
    seen = {}
    for status, (colour, _tooltip) in tray._ICON_STATES.items():
        seen[status] = tray._make_icon(status).getpixel((10, 32))  # inside the disc, left of the T
        assert seen[status] == colour
    assert len(set(seen.values())) == 3


def test_a_running_but_silent_server_is_not_labelled_active() -> None:
    assert tray._ICON_STATES["active"][1] != tray._ICON_STATES["working"][1]
    assert "Not Responding" in tray._ICON_STATES["working"][1]


def test_the_super_user_toggle_that_did_nothing_is_gone() -> None:
    assert not hasattr(tray.TrayState(), "super_user_mode")
    assert "Super-user" not in Path(tray.__file__).read_text(encoding="utf-8")


# --- Environment values that used to stop the agent from starting --------------


@pytest.mark.parametrize("raw", ["8MB", "", "abc", "1.5"])
def test_a_bad_log_size_variable_falls_back_to_the_default(monkeypatch, raw) -> None:
    monkeypatch.setenv("THOMAS_TRAY_LOG_MAX_BYTES", raw)

    assert tray._read_log_int_env("THOMAS_TRAY_LOG_MAX_BYTES", 12345) == 12345


def test_a_good_log_size_variable_is_used(monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_TRAY_LOG_MAX_BYTES", "4096")

    assert tray._read_log_int_env("THOMAS_TRAY_LOG_MAX_BYTES", 12345) == 4096


def test_a_slow_boot_is_not_declared_dead_at_thirty_seconds() -> None:
    assert tray.SERVER_STARTUP_TIMEOUT_S >= 60
