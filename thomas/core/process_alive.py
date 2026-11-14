"""Whether a process is still running, asked without sending it anything.

``os.kill(pid, 0)`` is the POSIX liveness probe. On Windows signal 0 is ``CTRL_C_EVENT``: the call goes through
``GenerateConsoleCtrlEvent`` and can interrupt every process sharing the console. ``agent_presence`` probed agents'
pids that way on every presence check the startup router makes, and on 2026-09-27 Thomas projects sharing a console
kept dying with KeyboardInterrupt; a Thomas project's own team found the cause. Here Windows is asked through
``OpenProcess`` and ``GetExitCodeProcess`` instead, the same question ``serve_instance_guard`` and
``thomas/server/overlay/store.py`` ask, and POSIX keeps ``os.kill(pid, 0)``.
"""

from __future__ import annotations

import os

_STILL_ACTIVE = 259
_ACCESS_DENIED = 5


def process_alive(pid: int | None) -> bool:
    """True when *pid* names a running process; False for a missing, finished or unusable pid."""
    if not pid or int(pid) <= 0:
        return False
    if os.name == "nt":
        return _windows_alive(int(pid))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is someone else's
    except (OSError, ValueError, OverflowError):
        return False
    return True


def _windows_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == _ACCESS_DENIED  # it exists; this account may not look at it
    try:
        code = wintypes.DWORD(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE  # a handle can outlive its process; the exit code cannot lie
    finally:
        kernel32.CloseHandle(handle)


__all__ = ["process_alive"]
