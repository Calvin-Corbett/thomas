"""A Thomas project's commands may stop only the processes that project started.

Measured 2026-09-27: every Thomas project's commands run here as thomas-agent. One project's team, cleaning up after
its own checks, listed every python process on the machine whose command line held "pytest" or "thomas" and ran
``taskkill /PID ... /F`` on the list. The same account owns every other project's test runs and this runner, so
nothing stopped it; the one process it could not stop belonged to another account.

The runner keeps each project's processes in a job of their own (``shell_runner._Job``), so it knows exactly which
processes are that project's. A command that stops processes must name them by id, and every id must be in the
project's job; a stop by name, by filter or through a pipe finds its targets only while it runs, so it is refused.
This reads the commands teams use to stop processes (taskkill, Stop-Process and its aliases, wmic, CIM Terminate). A
program that stops a process itself is not read here: the wall for that is an account per project.

Deliberately standalone, like the runner: no imports from ``thomas``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

_TASKKILL = re.compile(r"(?<![\w-])taskkill(?:\.exe)?(?P<args>[^&|\n]*)", re.I)
_STOP_PROCESS = re.compile(r"(?P<pipe>\|\s*)?(?<![\w-])(?:stop-process|spps)\b(?P<args>[^|;\n\"]*)", re.I)
_KILL = re.compile(r"(?P<pipe>\|\s*)?(?<![\w.$-])kill\b(?P<args>[^|;\n\"]*)", re.I)
_WMIC = re.compile(r"(?<![\w-])wmic\b(?P<args>[^&|\n]*)", re.I)
_CIM_TERMINATE = re.compile(r"invoke-(?:cim|wmi)method\b[^|;\n]*\bterminate\b", re.I)
_BY_NAME = re.compile(r"-(?:name|processname|inputobject)\b", re.I)
_LEADING_IDS = re.compile(r"^(?:\s+-id)?\s+(\d[\d\s,]*)", re.I)
_MAX_LISTED = 40
_WHY = (
    "Every Thomas project, the caged server and this shell run as the same account, so stopping a process this "
    "project did not start can end another project's work or Thomas itself. Stop your own processes by id "
    "(taskkill /PID <id> /F), taking the ids from the list below."
)


@dataclass(frozen=True)
class Stop:
    """What a command stops: the process ids it names, and why its targets cannot be known before it runs ("" if
    they can)."""

    ids: frozenset[int]
    unscoped: str


def _numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", text)}


def stops(command: str) -> Stop | None:
    """The processes *command* stops, or None when it stops none."""
    ids: set[int] = set()
    unscoped = ""
    found = False
    for match in _TASKKILL.finditer(command):
        args = match.group("args")
        if re.search(r"(?:^|\s)[/-](?:im|fi)(?:\s|$)", args, re.I):
            found, unscoped = True, unscoped or "taskkill /IM or /FI stops processes by name or filter"
        for value in re.findall(r"[/-]pid\s+(\S+)", args, re.I):
            found = True
            if value.isdigit():
                ids.add(int(value))
            else:
                unscoped = unscoped or f"taskkill /PID {value} names a process id computed while it runs"
    for pattern, verb in ((_STOP_PROCESS, "Stop-Process"), (_KILL, "kill")):
        for match in pattern.finditer(command):
            args = match.group("args")
            if match.group("pipe"):
                found, unscoped = True, unscoped or f"{verb} stops whatever a pipeline hands it"
            elif _BY_NAME.search(args):
                found, unscoped = True, unscoped or f"{verb} -Name stops processes by name"
            else:
                named = re.search(r"-id\s+([\d\s,]+)", args, re.I) or _LEADING_IDS.match(args)
                if named:
                    found = True
                    ids |= _numbers(named.group(1))
    for match in _WMIC.finditer(command):
        args = match.group("args")
        if re.search(r"\bprocess\b", args, re.I) and re.search(r"\b(?:delete|terminate)\b", args, re.I):
            found = True
            by_id = re.findall(r"processid\s*=\s*'?(\d+)", args, re.I)
            if by_id and not re.search(r"\bname\b|\blike\b|commandline", args, re.I):
                ids |= {int(n) for n in by_id}
            else:
                unscoped = unscoped or "wmic process ... delete stops the processes its query finds"
    if _CIM_TERMINATE.search(command):
        found, unscoped = True, unscoped or "Terminate through CIM or WMI stops the processes its query finds"
    return Stop(frozenset(ids), unscoped) if found else None


def pids_in_job(job: int, *, strict: bool = False) -> set[int]:
    """Every process in a Windows job; in strict mode, fail if the query cannot confirm it."""
    if os.name != "nt" or not job:
        return set()
    import ctypes
    from ctypes import wintypes

    class IdList(ctypes.Structure):
        _fields_ = [
            ("assigned", wintypes.DWORD),
            ("listed", wintypes.DWORD),
            ("ids", ctypes.c_size_t * 4096),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    listing = IdList()
    if not kernel32.QueryInformationJobObject(job, 3, ctypes.byref(listing), ctypes.sizeof(listing), None):
        if strict:
            raise OSError(ctypes.get_last_error(), "could not query job processes")
        return set()  # JobObjectBasicProcessIdList
    if strict and listing.listed > 4096:
        raise OSError("job process list exceeds query capacity")
    return {int(listing.ids[i]) for i in range(min(listing.listed, 4096))}


def describe(pid: int) -> str:
    """*pid* with its command line, or its program when the command line cannot be read."""
    if os.name != "nt":
        return str(pid)
    import ctypes
    from ctypes import wintypes

    class Unicode(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("maximum", ctypes.c_ushort), ("buffer", ctypes.c_void_p)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return str(pid)
    try:
        needed = ctypes.c_ulong(0)
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))  # ProcessCommandLineInformation
        if needed.value:
            raw = ctypes.create_string_buffer(needed.value)
            if ntdll.NtQueryInformationProcess(handle, 60, raw, needed.value, ctypes.byref(needed)) == 0:
                text = Unicode.from_buffer(raw)
                if text.buffer and text.length:
                    return f"{pid}  {ctypes.wstring_at(text.buffer, text.length // 2)[:200]}"
        size = wintypes.DWORD(1024)
        image = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return f"{pid}  {image.value}"
        return str(pid)
    finally:
        kernel32.CloseHandle(handle)


def refusal(command: str, own: set[int], *, describe: Callable[[int], str] = describe) -> str | None:
    """Why *command* may not run in a project whose processes are *own*, or None when it may."""
    stop = stops(command)
    if stop is None:
        return None
    if stop.unscoped:
        head = f"Refused: {stop.unscoped}, so which processes it stops is known only once it runs."
    else:
        foreign = sorted(stop.ids - own)
        if not foreign:
            return None
        head = f"Refused: this project did not start process {', '.join(str(pid) for pid in foreign)}."
    if own:
        listed = sorted(own)[:_MAX_LISTED]
        more = f"\n  ... and {len(own) - len(listed)} more" if len(own) > len(listed) else ""
        mine = "This project's processes now:\n" + "\n".join(f"  {describe(pid)}" for pid in listed) + more
    else:
        mine = "This project has no processes running now."
    return f"{head} {_WHY}\n{mine}"


__all__ = ["Stop", "describe", "pids_in_job", "refusal", "stops"]
