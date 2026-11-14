"""Which account a Windows sign-in was for: the one Thomas runs as, or another (Part 4 hardening, spec section 8.4).

scripts/breakglass_auth.py validates the credential your sign-in gave (LsaLogonUser, then LogonUserW) and, until this,
never asked whose it was: the prompt offers only your tile, but the LogonUserW fallback validates whatever account name
the credential carries. A window, and every card, is opened by that sign-in, so the token Windows hands back is now
compared with this process's own: the same account's SID, or no.

Windows only, standard library only. Protected with breakglass_auth.py (agent_safety.toml enforcement_scripts).
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

TOKEN_QUERY = 0x0008
TOKEN_USER = 1


def _libs() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    if sys.platform != "win32":
        raise OSError("account checks run on Windows only")
    from ctypes import wintypes

    advapi, kernel = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)]  # fmt: skip
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    return advapi, kernel


def token_sid(token: object) -> str:
    """The user SID a token belongs to, as text (S-1-5-21-...)."""
    from ctypes import wintypes

    advapi, kernel = _libs()
    size = wintypes.DWORD()
    advapi.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
    if not size.value:
        raise OSError(f"GetTokenInformation gave no size ({ctypes.get_last_error()})")
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, TOKEN_USER, buffer, size, ctypes.byref(size)):
        raise OSError(f"GetTokenInformation failed ({ctypes.get_last_error()})")
    sid = ctypes.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid is its first field
    text = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise OSError(f"ConvertSidToStringSidW failed ({ctypes.get_last_error()})")
    try:
        return str(text.value)
    finally:
        kernel.LocalFree(text)


def own_sid() -> str:
    """The user SID this process runs as."""
    from ctypes import wintypes

    advapi, kernel = _libs()
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise OSError(f"OpenProcessToken failed ({ctypes.get_last_error()})")
    try:
        return token_sid(token)
    finally:
        kernel.CloseHandle(token)


def same_account(
    token: object,
    said: str,
    *,
    close: bool = False,
    sid_of: Callable[[object], str] = token_sid,
    mine: Callable[[], str] = own_sid,
) -> tuple[bool, str]:
    """(True, *said*) when *token*, from a sign-in Windows accepted, is this process's own account; else (False,
    why). Closes *token* when *close*. A SID that cannot be read is a no."""
    try:
        theirs, ours = sid_of(token), mine()
    except OSError as exc:
        return False, f"the account that signed in could not be read: {exc}"
    finally:
        if close:
            _libs()[1].CloseHandle(token)
    if theirs != ours:
        return False, "the sign-in was for another account than the one Thomas runs as"
    return True, said


__all__ = ["own_sid", "same_account", "token_sid"]
