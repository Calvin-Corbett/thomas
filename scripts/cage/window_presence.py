"""Whether you are at the PC, read from inside your own session by the promoter (spec section 8.4).

Express's reader (scripts/cage/referee/presence_win.py) was written for a SYSTEM service in session 0, which can only
ask Windows about your session from outside, and takes idle time from the session's last-input time. Inside your session
that field can stay 0 for the console, which would read as hours idle. The promoter runs in your session, so it asks
directly: the session it runs in (``ProcessIdToSessionId``), its lock state and logon time (``WTSSessionInfoEx``,
through presence_win's binding), and your last input (``GetLastInputInfo``). The session id is
``<session>:<logon time>``, so signing out and in again is a different one. Nothing is written and nothing is started.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from scripts.cage.referee.presence import Presence
from scripts.cage.referee.presence_win import FLAG_LOCKED, FLAG_UNLOCKED, NativeWts, WtsApi


def own_session() -> int:
    """The Windows session this process runs in."""
    if sys.platform != "win32":
        raise OSError("presence is read on Windows only")
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel.GetCurrentProcessId.restype = wintypes.DWORD
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise OSError(f"ProcessIdToSessionId failed ({ctypes.get_last_error()})")
    return int(session.value)


def idle_seconds() -> float:
    """Seconds since your last keyboard or mouse input in this session."""
    if sys.platform != "win32":
        raise OSError("presence is read on Windows only")
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user, kernel = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32")
    user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
    user.GetLastInputInfo.restype = wintypes.BOOL
    kernel.GetTickCount.restype = wintypes.DWORD
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not user.GetLastInputInfo(ctypes.byref(info)):
        raise OSError(f"GetLastInputInfo failed ({ctypes.get_last_error()})")
    return ((int(kernel.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF) / 1000.0


class InSession:
    """A ``PresenceSource`` (scripts/cage/referee/presence.py) for the session the promoter runs in."""

    def __init__(
        self,
        api: WtsApi | None = None,
        *,
        session: Callable[[], int] = own_session,
        idle: Callable[[], float] = idle_seconds,
    ) -> None:
        self._api = api
        self._session, self._idle = session, idle

    def state(self) -> Presence:
        api = self._api or NativeWts()
        number = self._session()
        info = api.session_info(number)
        if info.flags not in (FLAG_LOCKED, FLAG_UNLOCKED):
            raise OSError("the session's lock state is unknown")
        return Presence(info.flags == FLAG_LOCKED, float(self._idle()), f"{number}:{info.logon_time}")


__all__ = ["InSession", "idle_seconds", "own_session"]
