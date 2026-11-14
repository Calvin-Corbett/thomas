"""Run one command as the runner account, in a kill-on-close job, on Windows (review B1).

:func:`run_as` logs the ``thomas-runner`` account on with a credential kept in the checker's own credential store --
which the runner account cannot read -- and starts the command suspended inside a job object with KILL_ON_JOB_CLOSE,
so every process the test starts is in the job before any of them runs, and the whole tree is ended when the job
closes. The pass/fail signal is the JUnit report the test writes into its copy (which the runner may write); this
captures stdout and stderr to a temporary file only for the diagnostic line.

``CreateProcessWithLogonW`` cannot inherit handles and limits its command line to 1024 characters. A short Python
child reads the full argv from a file in the job's copy and captures output there. This module changes no account or
ACL itself.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

from thomas.server.proof.environment import NOT_STARTED, TIMED_OUT

if TYPE_CHECKING:
    from scripts.cage.checker_runner import Identity

_LOGON_WITH_PROFILE = 0x00000001
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CRED_TYPE_GENERIC = 1
_KILL_ON_JOB_CLOSE = 0x2000
_JOB_LIMIT_INFO = 9  # JobObjectExtendedLimitInformation
_JOB_BASIC_ACCOUNTING = 1  # JobObjectBasicAccountingInformation
_TAIL_BYTES = 8192


class _StartupInfo(ctypes.Structure):
    _fields_ = (
        [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR)]
        + [("title", wintypes.LPWSTR)]
        + [(name, wintypes.DWORD) for name in ("x", "y", "xsize", "ysize", "xchars", "ychars", "fill", "flags")]
        + [("show", wintypes.WORD), ("cb_reserved2", wintypes.WORD), ("reserved2", ctypes.c_void_p)]
        + [("stdinput", wintypes.HANDLE), ("stdoutput", wintypes.HANDLE), ("stderror", wintypes.HANDLE)]
    )


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE),
        ("thread", wintypes.HANDLE),
        ("pid", wintypes.DWORD),
        ("tid", wintypes.DWORD),
    ]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("per_process_time", ctypes.c_int64),
        ("per_job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("min_ws", ctypes.c_size_t),
        ("max_ws", ctypes.c_size_t),
        ("active", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimit),
        ("io", ctypes.c_uint64 * 6),
        ("process_mem", ctypes.c_size_t),
        ("job_mem", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("user", "kernel", "period_user", "period_kernel")] + [
        (name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")
    ]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD),
        ("type", wintypes.DWORD),
        ("target", wintypes.LPWSTR),
        ("comment", wintypes.LPWSTR),
        ("last_written", ctypes.c_uint64),
        ("blob_size", wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_char)),
        ("persist", wintypes.DWORD),
        ("attribute_count", wintypes.DWORD),
        ("attributes", ctypes.c_void_p),
        ("target_alias", wintypes.LPWSTR),
        ("username", wintypes.LPWSTR),
    ]


def _check(ok: object) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _read_credential(target: str) -> tuple[str, str]:
    """The (username, password) the setup stored for the runner, from the checker's credential store."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.c_void_p()
    _check(advapi.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)))
    try:
        cred = ctypes.cast(pointer, ctypes.POINTER(_Credential)).contents
        password = ctypes.string_at(cred.blob, cred.blob_size).decode("utf-16-le") if cred.blob_size else ""
        username = cred.username or ""
        return username, password
    finally:
        advapi.CredFree(pointer)


def _env_block(env: dict[str, str]) -> ctypes.Array:
    joined = "".join(f"{key}={value}\0" for key, value in sorted(env.items())) + "\0"
    return ctypes.create_unicode_buffer(joined, len(joined))


def _account(identity: Identity, cred_username: str) -> tuple[str, str]:
    name = cred_username or identity.account
    domain, _, user = name.replace("/", "\\").rpartition("\\")
    return (user or name), (domain or ".")


def _configure_apis(kernel: ctypes.WinDLL, ntdll: ctypes.WinDLL, advapi: ctypes.WinDLL) -> None:
    """Declare pointer-sized handles explicitly; ctypes otherwise treats returned handles as 32-bit ints."""
    advapi.CreateProcessWithLogonW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInfo),
    )
    advapi.CreateProcessWithLogonW.restype = wintypes.BOOL
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)


def _console(executable: str) -> str:
    """``python.exe`` beside a ``pythonw.exe``, else *executable* unchanged.

    The checker runs under the venv's ``pythonw.exe``, and that launcher loads user32 and gdi32 as it starts: as the
    runner, on the checker's non-interactive station, their start-up fails and the process ends 0xC0000142 before
    any test runs (2026-10-23, every check since 08:28, the private desktop included). The console launcher and the
    interpreters load neither.
    """
    path = Path(executable)
    console = path.with_name("python.exe")
    return str(console) if path.name.lower() == "pythonw.exe" and console.is_file() else executable


def _child_command(payload: Path) -> ctypes.Array:
    """Keep the logon API's line short; the runner reads its exact argv from a file.

    The runner's script is written beside its payload rather than run from this file: scripts\\cage keeps a protected
    ACL the runner is not on, so ``python checker_launch.py`` ended "can't open file" (exit 2, 2026-10-23).
    """
    child = payload.with_suffix(".py")
    child.write_text(_CHILD_SOURCE, encoding="utf-8")
    line = subprocess.list2cmdline([_console(sys.executable), "-I", str(child), str(payload)])
    if len(line) + 1 > 1024:
        raise OSError("the runner's child command exceeds the Windows logon command-line limit")
    return ctypes.create_unicode_buffer(line)


def run_as(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float, identity: Identity
) -> tuple[int, str]:
    """Run *command* as the runner account; return its exit code (or a sentinel) and the tail of its output."""
    if os.name != "nt":
        raise OSError("the runner launcher requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _configure_apis(kernel, ntdll, advapi)
    username, password = _read_credential(identity.credential)
    user, domain = _account(identity, username)
    temp_dir = Path(env.get("THOMAS_DATA_DIR") or cwd)
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="runner-", suffix=".json", dir=str(temp_dir))
    os.close(fd)
    payload = Path(name)
    out = payload.with_suffix(".out")
    try:
        command = [_console(command[0]), *command[1:]] if command else command
        payload.write_text(json.dumps({"command": command, "out": str(out)}), encoding="utf-8")
        line = _child_command(payload)
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(_StartupInfo)
        info = _ProcessInfo()
        flags = _CREATE_SUSPENDED | _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT
        from scripts.cage.checker_desktop import runner_desktop

        with runner_desktop(identity.account) as desktop:
            startup.desktop = desktop
            _check(
                advapi.CreateProcessWithLogonW(
                    user,
                    domain,
                    password,
                    _LOGON_WITH_PROFILE,
                    None,
                    line,
                    flags,
                    _env_block(env),
                    str(cwd),
                    ctypes.byref(startup),
                    ctypes.byref(info),
                )
            )
            job = kernel.CreateJobObjectW(None, None)
            try:
                _check(job)
                limit = _ExtendedLimit()
                limit.basic.flags = _KILL_ON_JOB_CLOSE
                _check(kernel.SetInformationJobObject(job, _JOB_LIMIT_INFO, ctypes.byref(limit), ctypes.sizeof(limit)))
                _check(kernel.AssignProcessToJobObject(job, info.process))
                if ntdll.NtResumeProcess(info.process) != 0:
                    raise OSError("the runner process could not resume")
                wait = kernel.WaitForSingleObject(info.process, min(int(timeout_s * 1000), 0xFFFFFFFE))
                if wait == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
                timed_out = wait == 0x102
                code = wintypes.DWORD()
                _check(kernel.GetExitCodeProcess(info.process, ctypes.byref(code)))
                exit_code = TIMED_OUT if timed_out else int(code.value)
            finally:
                _drain(kernel, job)
                for handle in (info.thread, info.process):
                    if handle:
                        kernel.CloseHandle(handle)
        text = _tail(out)
        if timed_out:
            return TIMED_OUT, f"the runner's test did not finish within {timeout_s:g}s"
        if exit_code == _CHILD_NOT_STARTED:
            return NOT_STARTED, text.strip() or "the runner could not start the test command"
        return exit_code, text
    finally:
        payload.unlink(missing_ok=True)
        payload.with_suffix(".py").unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def _drain(kernel: ctypes.WinDLL, job: int) -> None:
    if not job:
        return
    try:
        kernel.TerminateJobObject(job, 1)
        end = time.monotonic() + 5.0
        while time.monotonic() < end:
            accounting = _Accounting()
            if not kernel.QueryInformationJobObject(
                job, _JOB_BASIC_ACCOUNTING, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            ):
                break
            if accounting.active == 0:
                break
            time.sleep(0.01)
    finally:
        kernel.CloseHandle(job)


def _tail(out: Path) -> str:
    try:
        with open(out, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - _TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return ""


# The runner reads the checked command only after logon; the parent alone chooses its environment and job. A command
# that cannot start exits _CHILD_NOT_STARTED, never pytest's 1, so its error reaches the answer instead of a missing
# report (2026-10-23: "its report has no test case").
_CHILD_NOT_STARTED = 126
_CHILD_SOURCE = f"""import json, subprocess, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
with open(data["out"], "wb") as output:
    try:
        code = subprocess.call(data["command"], stdout=output, stderr=subprocess.STDOUT)
    except OSError as exc:
        output.write(("the runner could not start the test command: " + str(exc)).encode("utf-8", errors="replace"))
        code = {_CHILD_NOT_STARTED}
sys.exit(code)
"""


__all__ = ["run_as"]
