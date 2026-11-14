"""Where the keeper may write: an owner-only folder, reached through no link, outside the place and the cage (R3).

``why_not_private`` is the one check for the keep, the work folder, the state folder and a ``state --out`` file's
folder. It says why a folder is refused, or returns None:

- no part of the path that exists is a link (a junction or symlink would put the writes somewhere unchecked);
- the real path (links resolved) is not the place being read or inside it, nor inside a folder the caged account
  reads (``CAGE_ROOTS``);
- the folder's access list (before the folder exists, its nearest existing parent's, which a new folder inherits)
  lets nobody read but you, SYSTEM, Administrators and the owner-only entries Windows itself uses. A Codex sandbox
  group, the caged account or Everyone on that list refuses it. Read on Windows only; elsewhere this part is skipped.
"""

from __future__ import annotations

import functools
import os
import stat
import sys
from collections.abc import Iterable
from pathlib import Path

from scripts.cage.referee.nofollow import REPARSE

CAGE_ROOTS = (  # folders the caged account can read (design 2.1); no capture or working copy goes under them (R3)
    r"C:\ProgramData\ThomasCage\shell",
    r"C:\ProgramData\ThomasCage\outbox",
    r"C:\Users\thomas-agent",
    r"C:\Users\corbe\Thomas",
    r"C:\Users\corbe\.thomas",
)
OWNER_ONLY = {  # entries that let nobody else in: the machine itself, its administrators, and owner placeholders
    "S-1-5-18": "SYSTEM",
    "S-1-5-32-544": "Administrators",
    "S-1-3-4": "OWNER RIGHTS",
    "S-1-3-0": "CREATOR OWNER",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464": "TrustedInstaller",
}
KNOWN = {**OWNER_ONLY, "S-1-1-0": "Everyone", "S-1-5-11": "Authenticated Users", "S-1-5-32-545": "Users"}
# read data or list a folder, change its access list or owner, generic all or generic read
READ_RIGHTS = 0x1 | 0x40000 | 0x80000 | 0x10000000 | 0x80000000
ALLOW, DENY, ALLOW_CALLBACK, DENY_CALLBACK = 0, 1, 9, 10


def real(path: str | Path) -> str:
    """The path with every link resolved, for comparing where a write would really land."""
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path)))).rstrip("\\/")


def existing(path: str | Path) -> Path:
    """``path`` itself, or its nearest parent that exists."""
    here = Path(os.path.abspath(path))
    while not os.path.lexists(here) and here.parent != here:
        here = here.parent
    return here


def link_in(path: str | Path) -> Path | None:
    """The first part of ``path`` (from the drive down) that is a junction or symlink, or None."""
    here = Path(os.path.abspath(path))
    for part in [*reversed(here.parents), here]:
        try:
            info = os.lstat(part)
        except FileNotFoundError:
            return None  # nothing below a missing part exists either
        if getattr(info, "st_file_attributes", 0) & REPARSE or stat.S_ISLNK(info.st_mode):
            return part
    return None


def strangers(owner: str | None, aces: list[tuple[int, int, str]] | None, me: str) -> list[str]:
    """Who besides ``me`` and ``OWNER_ONLY`` may read, from an owner SID and ``(kind, mask, sid)`` access entries.

    ``aces`` None is a folder with no access list at all, which Windows reads as "everyone, everything". An entry
    kind this does not parse (an object entry) is counted as a stranger, never skipped.
    """
    if aces is None:
        return ["anyone (no access list)"]
    allowed, found = {me, *OWNER_ONLY}, set()
    for kind, mask, sid in aces:
        if kind in (DENY, DENY_CALLBACK):
            continue  # a deny entry never lets anyone in
        if kind not in (ALLOW, ALLOW_CALLBACK):
            found.add(f"an access entry of kind {kind}")
        elif mask & READ_RIGHTS and sid not in allowed:
            found.add(sid)
    if owner and owner not in allowed:
        found.add(f"{owner} (owner)")
    return sorted(found)


@functools.cache
def _api():
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ptr = ctypes.POINTER(ctypes.c_void_p)
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ptr, ptr, ptr, ptr, ptr]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ptr]
    adv.GetAce.restype = wintypes.BOOL
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    adv.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertStringSidToSidW.restype = wintypes.BOOL
    adv.LookupAccountSidW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR]
    adv.LookupAccountSidW.argtypes += [ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR]
    adv.LookupAccountSidW.argtypes += [ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_int)]
    adv.LookupAccountSidW.restype = wintypes.BOOL
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    adv.GetTokenInformation.argtypes += [ctypes.POINTER(wintypes.DWORD)]
    adv.GetTokenInformation.restype = wintypes.BOOL
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, adv, k32


def _sid_text(sid: int | None) -> str | None:
    if not sid:
        return None
    ctypes, _, adv, k32 = _api()
    text = ctypes.c_void_p()
    if not adv.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise OSError(ctypes.get_last_error(), "a security id could not be read")
    try:
        return ctypes.wstring_at(text.value)
    finally:
        k32.LocalFree(text)


@functools.cache
def my_sid() -> str:
    """The security id of the account this process runs as, from its own token."""
    ctypes, wintypes, adv, k32 = _api()
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise OSError(ctypes.get_last_error(), "this process's token could not be read")
    try:
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser: asks for the size first
        buf = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "this process's account could not be read")
        return _sid_text(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value) or ""
    finally:
        k32.CloseHandle(token)


def read_access(path: Path) -> tuple[str | None, list[tuple[int, int, str]] | None]:
    """A file or folder's owner SID and its access entries as ``(kind, mask, sid)``; entries None for no list."""
    ctypes, wintypes, adv, k32 = _api()

    class AclHeader(ctypes.Structure):
        _fields_ = [("revision", ctypes.c_ubyte), ("sbz1", ctypes.c_ubyte), ("size", ctypes.c_ushort)] + [
            ("count", ctypes.c_ushort),
            ("sbz2", ctypes.c_ushort),
        ]

    class AceHeader(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", ctypes.c_ushort)]

    owner, dacl, sd = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    # SE_FILE_OBJECT; OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
    code = adv.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, ctypes.byref(owner), None, ctypes.byref(dacl), None,
                                     ctypes.byref(sd))  # fmt: skip
    if code:
        raise OSError(code, f"the access list of {path} could not be read (Windows error {code})")
    try:
        if not dacl.value:
            return _sid_text(owner.value), None
        aces = []
        for number in range(ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents.count):
            ace = ctypes.c_void_p()
            if not adv.GetAce(dacl, number, ctypes.byref(ace)):
                raise OSError(ctypes.get_last_error(), f"access entry {number} of {path} could not be read")
            kind = ctypes.cast(ace, ctypes.POINTER(AceHeader)).contents.kind
            if kind in (ALLOW, DENY, ALLOW_CALLBACK, DENY_CALLBACK):  # header, mask, then the SID
                mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD)).contents.value
                aces.append((kind, mask, _sid_text(ace.value + 8) or ""))
            else:
                aces.append((kind, 0, ""))
        return _sid_text(owner.value), aces
    finally:
        k32.LocalFree(sd)


@functools.cache
def _named(sid: str) -> str:
    """``name (sid)`` when Windows can name a SID, else the SID alone. Only for the words of a refusal."""
    if sid in KNOWN:
        return f"{KNOWN[sid]} ({sid})"
    if not sid.startswith("S-"):
        return sid
    ctypes, wintypes, adv, k32 = _api()
    binary = ctypes.c_void_p()
    if not adv.ConvertStringSidToSidW(sid, ctypes.byref(binary)):
        return sid
    try:
        name, domain = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
        sizes, use = (wintypes.DWORD(256), wintypes.DWORD(256)), ctypes.c_int()
        found = adv.LookupAccountSidW(None, binary, name, ctypes.byref(sizes[0]), domain, ctypes.byref(sizes[1]),
                                      ctypes.byref(use))  # fmt: skip
        return f"{name.value} ({sid})" if found and name.value else sid
    finally:
        k32.LocalFree(binary)


def readers_besides_you(path: Path) -> list[str]:
    """Who besides you (and SYSTEM, Administrators) can read what is written under ``path``. Windows only."""
    if sys.platform != "win32":
        return []
    owner, aces = read_access(existing(path))
    out = []
    for who in strangers(owner, aces, my_sid()):
        sid, owns = (who[: -len(" (owner)")], True) if who.endswith(" (owner)") else (who, False)
        out.append(_named(sid) + (", the owner" if owns else ""))
    return out


def why_not_private(path: str | Path, places: Iterable[str | Path] = ()) -> str | None:
    """Why the keeper may not write under ``path``, or None when it may (see the module notes)."""
    try:
        link = link_in(path)
        if link is not None:
            return f"{path} passes through a link ({link}); captures never go through one"
        here = real(path)
        for root in [real(p) for p in places] + [real(r) for r in CAGE_ROOTS]:
            if here == root or here.startswith(root + os.sep):
                return f"{path} is inside {root}; captures never go there"
        others = readers_besides_you(Path(path))
    except OSError as exc:
        return f"{path} could not be checked ({exc})"
    if others:
        return f"{path} can be read by {', '.join(others)}; captures go only where nobody but you can read"
    return None
