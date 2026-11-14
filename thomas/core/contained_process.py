"""Own a Windows subprocess tree until its agent run ends, and run a command on a clock that holds its whole tree."""

from __future__ import annotations

import contextlib
import ctypes
import locale
import os
import signal
import subprocess
import tempfile
import threading
from ctypes import wintypes
from typing import IO, Any

_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_TAIL_BYTES = 8192


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class OwnedWindowsJob:
    """Closing the job handle terminates the lead and all descendants."""

    def __init__(self, process: Any) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows jobs are available only on Windows")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel = kernel
        self._lock = threading.Lock()
        self._handle = kernel.CreateJobObjectW(None, None)
        if not self._handle:
            process.kill()
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = _ExtendedLimit()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(self._handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except OSError:
            process.kill()
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._kernel.CloseHandle(self._handle)
                self._handle = None


def _resume(process: Any) -> None:
    """Let a process created suspended run (psutil's resume uses the same call)."""
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    status = ntdll.NtResumeProcess(int(process._handle))
    if status != 0:
        raise OSError(f"NtResumeProcess failed: status {status & 0xFFFFFFFF:#x}")


def _end_tree(process: subprocess.Popen, job: OwnedWindowsJob | None) -> None:
    if job is not None:
        job.close()  # kill-on-close: the command and every process it started
    elif os.name != "nt":
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


def _tail(handle: IO[bytes]) -> str:
    handle.seek(0, os.SEEK_END)
    handle.seek(max(0, handle.tell() - _TAIL_BYTES))
    return handle.read().decode(locale.getpreferredencoding(False), errors="replace").replace("\r\n", "\n")


def run_contained(command: str, *, cwd: str, timeout: float) -> tuple[int | None, str, str]:
    """Run a shell command line on a clock that holds everything it starts.

    Output goes to temporary files, never pipes, so nothing the command leaves running can keep the caller waiting on
    a pipe. On Windows the command starts suspended inside a kill-on-close job, so every process it starts is in the
    job before any of them runs; elsewhere it leads its own process group. When the command ends or the clock runs
    out, the job (or group) is killed. Returns the exit code (None when the clock ran out) and the last 8 KB of stdout
    and of stderr. Raises OSError when the command cannot be started.
    """
    windows = os.name == "nt"
    flags: dict[str, Any] = (
        {"creationflags": _CREATE_SUSPENDED | _CREATE_NO_WINDOW} if windows else {"start_new_session": True}
    )
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=out, stderr=err, **flags)
        job = None
        try:
            if windows:
                job = OwnedWindowsJob(proc)
                _resume(proc)
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            _end_tree(proc, job)
        return code, _tail(out), _tail(err)
