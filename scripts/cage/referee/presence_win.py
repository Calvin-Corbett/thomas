"""The Windows reader for owner presence, through ctypes and the Terminal Services session API.

The referee runs as SYSTEM in session 0, where ``GetLastInputInfo`` sees only its own session, so it asks about your
session instead: ``WTSQuerySessionInformationW`` with ``WTSSessionInfoEx`` gives the lock state (``SessionFlags``), the
logon time and the last-input and current times of the active console session. The logon session id the grant is bound
to is ``<session number>:<logon time>``, so signing out and in again is a different one. Nothing is written and no
process is started. ``WtsApi`` is the seam the tests fake; ``NativeWts`` is the real binding and raises ``OSError`` off
Windows. Standard library only.
"""

from __future__ import annotations

import ctypes
import sys
from typing import NamedTuple, Protocol

from .presence import Presence

NO_SESSION = 0xFFFFFFFF
WTS_SESSION_INFO_EX = 25  # WTSSessionInfoEx
FLAG_LOCKED, FLAG_UNLOCKED = 0, 1  # WTS_SESSIONSTATE_LOCK and WTS_SESSIONSTATE_UNLOCK (Windows 8 and later)
TICKS = 10_000_000  # FILETIME ticks per second


class SessionInfo(NamedTuple):
    flags: int
    logon_time: int  # 100 ns ticks
    last_input: int  # 0 when there has been no input since logon
    current: int


class WtsApi(Protocol):
    def active_session(self) -> int: ...

    def session_info(self, session_id: int) -> SessionInfo: ...


class WindowsPresence:
    """``PresenceSource`` for the active console session."""

    def __init__(self, api: WtsApi | None = None) -> None:
        self._api = api or NativeWts()

    def state(self) -> Presence:
        session = self._api.active_session()
        if session == NO_SESSION:
            raise OSError("no one is signed in at the console")
        info = self._api.session_info(session)
        if info.flags not in (FLAG_LOCKED, FLAG_UNLOCKED):
            raise OSError("the session's lock state is unknown")
        since = info.last_input or info.logon_time
        return Presence(info.flags == FLAG_LOCKED, (info.current - since) / TICKS, f"{session}:{info.logon_time}")


class NativeWts:
    """The real binding. Every prototype is set, so a 64-bit pointer is never cut to an int."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("the Windows presence reader only runs on Windows")
        from ctypes import wintypes

        class Level1(ctypes.Structure):
            _fields_ = [
                ("SessionId", wintypes.DWORD),
                ("SessionState", ctypes.c_int),
                ("SessionFlags", ctypes.c_long),
                ("WinStationName", ctypes.c_wchar * 33),
                ("UserName", ctypes.c_wchar * 21),
                ("DomainName", ctypes.c_wchar * 18),
                ("LogonTime", ctypes.c_longlong),
                ("ConnectTime", ctypes.c_longlong),
                ("DisconnectTime", ctypes.c_longlong),
                ("LastInputTime", ctypes.c_longlong),
                ("CurrentTime", ctypes.c_longlong),
                ("Counters", wintypes.DWORD * 6),
            ]

        class InfoEx(ctypes.Structure):
            _fields_ = [("Level", wintypes.DWORD), ("Data", Level1)]

        self._type = InfoEx
        kernel, wts = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("wtsapi32", use_last_error=True)
        self._active = kernel.WTSGetActiveConsoleSessionId
        self._active.argtypes, self._active.restype = [], wintypes.DWORD
        self._query = wts.WTSQuerySessionInformationW
        self._query.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._query.restype = wintypes.BOOL
        self._free = wts.WTSFreeMemory
        self._free.argtypes, self._free.restype = [ctypes.c_void_p], None

    def active_session(self) -> int:
        return int(self._active())

    def session_info(self, session_id: int) -> SessionInfo:
        from ctypes import wintypes

        buffer, size = ctypes.c_void_p(), wintypes.DWORD()
        if not self._query(None, session_id, WTS_SESSION_INFO_EX, ctypes.byref(buffer), ctypes.byref(size)):
            raise OSError(f"WTSQuerySessionInformationW failed ({ctypes.get_last_error()})")
        try:
            if not buffer.value or size.value < ctypes.sizeof(self._type):
                raise OSError("the session information was shorter than expected")
            data = self._type.from_address(buffer.value).Data
            flags = data.SessionFlags & 0xFFFFFFFF
            return SessionInfo(flags, data.LogonTime, data.LastInputTime, data.CurrentTime)
        finally:
            self._free(buffer)
