"""The runner starts on an isolated desktop rather than the checker's task desktop."""

from __future__ import annotations

import ctypes
import inspect
import os

import pytest
from scripts.cage import checker_desktop, checker_launch


@pytest.mark.skipif(os.name != "nt", reason="Windows window-station ACLs")
def test_runner_gets_a_private_desktop_and_station_grant_is_reverted() -> None:
    import win32api
    import win32security
    import win32service

    station = win32service.GetProcessWindowStation()
    current_desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())

    def acl(handle: object) -> str:
        descriptor = win32security.GetSecurityInfo(handle, win32security.SE_WINDOW_OBJECT, 4)
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor, 1, 4)

    launch_source = inspect.getsource(checker_launch.run_as)
    assert "with runner_desktop(identity.account) as desktop:" in launch_source
    assert "startup.desktop = desktop" in launch_source
    assert launch_source.index("with runner_desktop(identity.account) as desktop:") < launch_source.index(
        "_drain(kernel, job)"
    )
    assert launch_source.index("_drain(kernel, job)") < launch_source.index("text = _tail(out)")
    station_before = acl(station)
    desktop_before = acl(current_desktop)
    try:
        with checker_desktop.runner_desktop("thomas-runner") as name:
            assert "\\ThomasRunner-" in name
            assert acl(station) != station_before
            assert acl(current_desktop) == desktop_before
            assert ctypes.sizeof(checker_launch._StartupInfo) >= ctypes.sizeof(ctypes.c_void_p)
            info = checker_launch._StartupInfo()
            info.desktop = name
            assert info.desktop == name
    finally:
        assert acl(station) == station_before
        assert acl(current_desktop) == desktop_before


@pytest.mark.skipif(os.name != "nt", reason="Windows window-station ACLs")
def test_station_grant_is_removed_when_launch_raises() -> None:
    import win32security
    import win32service

    station = win32service.GetProcessWindowStation()

    def acl() -> str:
        descriptor = win32security.GetSecurityInfo(station, win32security.SE_WINDOW_OBJECT, 4)
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor, 1, 4)

    before = acl()
    with pytest.raises(RuntimeError, match="launch failed"):
        with checker_desktop.runner_desktop("thomas-runner"):
            raise RuntimeError("launch failed")
    assert acl() == before


def test_the_runner_is_started_with_the_console_python_not_pythonw(tmp_path, monkeypatch) -> None:
    # The venv's pythonw.exe loads user32 as it starts; as the runner that start-up failed with 0xC0000142 (2026-10-23).
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_bytes(b"")
    (scripts / "pythonw.exe").write_bytes(b"")
    windowed = str(scripts / "pythonw.exe")
    assert checker_launch._console(windowed) == str(scripts / "python.exe")
    assert checker_launch._console(str(scripts / "python.exe")) == str(scripts / "python.exe")
    assert checker_launch._console("git") == "git"
    monkeypatch.setattr(checker_launch.sys, "executable", windowed)
    line = checker_launch._child_command(tmp_path / "payload.json").value
    assert "pythonw.exe" not in line and str(scripts / "python.exe") in line
    launch_source = inspect.getsource(checker_launch.run_as)
    assert "command = [_console(command[0]), *command[1:]]" in launch_source


def test_a_lone_pythonw_is_kept_when_no_console_python_sits_beside_it(tmp_path) -> None:
    (tmp_path / "pythonw.exe").write_bytes(b"")
    assert checker_launch._console(str(tmp_path / "pythonw.exe")) == str(tmp_path / "pythonw.exe")


def test_the_runner_gets_the_station_rights_user32_needs_and_no_more() -> None:
    # Measured 2026-10-23: without WINSTA_EXITWINDOWS (0x0040) libcrypto's user32 start-up failed in the runner.
    station, desktop = checker_desktop._WINSTA_RUN, checker_desktop._DESKTOP_RUN
    assert station & 0x0020 and station & 0x0040  # WINSTA_ACCESSGLOBALATOMS, WINSTA_EXITWINDOWS
    assert not station & (0x0004 | 0x0008 | 0x0010)  # no clipboard, desktop creation or attribute writes
    assert not desktop & 0x0100  # never DESKTOP_SWITCHDESKTOP
