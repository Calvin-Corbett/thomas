"""Give a logged-on test runner a private desktop in the checker's window station."""

from __future__ import annotations

import ctypes
import threading
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator

_DACL_SECURITY_INFORMATION = 4
_SE_WINDOW_OBJECT = 7
_UOI_NAME = 2
_GRANT_ACCESS = 1
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_USER = 1
# user32 starts in the runner only with WINSTA_ACCESSGLOBALATOMS (0x0020) and WINSTA_EXITWINDOWS (0x0040) on the
# station, measured by check jobs on 2026-10-23: without EXITWINDOWS its start-up failed ("DLL initialization routine
# failed", libcrypto via ssl). No clipboard, desktop creation or attribute writes; the grant lasts for the run. The
# desktop is the run's own and closed after it; the runner may never switch to it.
_WINSTA_RUN = 0x0001 | 0x0002 | 0x0020 | 0x0040 | 0x0100 | 0x0200 | 0x00020000
_DESKTOP_RUN = 0x00FF | 0x00020000
_STATION_LOCK = threading.Lock()


class _Trustee(ctypes.Structure):
    _fields_ = [
        ("multiple", ctypes.c_void_p),
        ("operation", wintypes.DWORD),
        ("form", wintypes.DWORD),
        ("type", wintypes.DWORD),
        ("name", ctypes.c_void_p),
    ]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("permissions", wintypes.DWORD),
        ("mode", wintypes.DWORD),
        ("inheritance", wintypes.DWORD),
        ("trustee", _Trustee),
    ]


def _api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetProcessWindowStation.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetUserObjectInformationW.restype = wintypes.BOOL
    user.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    user.CreateDesktopW.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.CloseDesktop.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    adv.LookupAccountNameW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    adv.LookupAccountNameW.restype = wintypes.BOOL
    adv.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    adv.GetSecurityInfo.restype = wintypes.DWORD
    adv.SetEntriesInAclW.argtypes = [
        wintypes.ULONG,
        ctypes.POINTER(_ExplicitAccess),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    adv.SetEntriesInAclW.restype = wintypes.DWORD
    adv.SetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    adv.SetSecurityInfo.restype = wintypes.DWORD
    return user, adv, kernel


def _error(code: int) -> None:
    if code:
        raise ctypes.WinError(code)


def _runner_sid(adv, account: str) -> ctypes.Array:
    sid_size = wintypes.DWORD(0)
    domain_size = wintypes.DWORD(0)
    use = wintypes.DWORD()
    adv.LookupAccountNameW(
        None, account, None, ctypes.byref(sid_size), None, ctypes.byref(domain_size), ctypes.byref(use)
    )
    if ctypes.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(domain_size.value)
    if not adv.LookupAccountNameW(
        None, account, sid, ctypes.byref(sid_size), domain, ctypes.byref(domain_size), ctypes.byref(use)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return sid


def _grant(adv, kernel, handle: int, sid: ctypes.Array, permissions: int) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
    descriptor = ctypes.c_void_p()
    original = ctypes.c_void_p()
    _error(
        adv.GetSecurityInfo(
            handle,
            _SE_WINDOW_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(original),
            None,
            ctypes.byref(descriptor),
        )
    )
    updated = ctypes.c_void_p()
    entry = _ExplicitAccess(
        permissions, _GRANT_ACCESS, 0, _Trustee(None, 0, _TRUSTEE_IS_SID, _TRUSTEE_IS_USER, ctypes.addressof(sid))
    )
    try:
        _error(adv.SetEntriesInAclW(1, ctypes.byref(entry), original, ctypes.byref(updated)))
        _error(adv.SetSecurityInfo(handle, _SE_WINDOW_OBJECT, _DACL_SECURITY_INFORMATION, None, None, updated, None))
        return descriptor, original
    except BaseException:
        kernel.LocalFree(descriptor)
        raise
    finally:
        if updated:
            kernel.LocalFree(updated)


@contextmanager
def runner_desktop(account: str) -> Iterator[str]:
    """Hold a private desktop until the runner exits, then remove its station grant."""
    with _STATION_LOCK:
        yield from _runner_desktop(account)


def _runner_desktop(account: str) -> Iterator[str]:
    user, adv, kernel = _api()
    station = user.GetProcessWindowStation()
    if not station:
        raise ctypes.WinError(ctypes.get_last_error())
    station_name = ctypes.create_unicode_buffer(256)
    length = wintypes.DWORD()
    if not user.GetUserObjectInformationW(
        station, _UOI_NAME, station_name, ctypes.sizeof(station_name), ctypes.byref(length)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    sid = _runner_sid(adv, account)
    name = f"ThomasRunner-{uuid.uuid4().hex}"
    desktop = user.CreateDesktopW(name, None, None, 0, _DESKTOP_RUN | 0x00040000, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    saved = None
    try:
        desktop_sd, _ = _grant(adv, kernel, desktop, sid, _DESKTOP_RUN)
        kernel.LocalFree(desktop_sd)
        saved, original = _grant(adv, kernel, station, sid, _WINSTA_RUN)
        yield f"{station_name.value}\\{name}"
    finally:
        try:
            if desktop:
                user.CloseDesktop(desktop)
        finally:
            if saved:
                try:
                    _error(
                        adv.SetSecurityInfo(
                            station, _SE_WINDOW_OBJECT, _DACL_SECURITY_INFORMATION, None, None, original, None
                        )
                    )
                finally:
                    kernel.LocalFree(saved)
