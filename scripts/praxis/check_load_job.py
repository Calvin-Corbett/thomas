"""The Windows job a load run joins (``check_load.py``): its own CPU, and every process it started ends with it.

When ``check_load`` runs as a script it first joins a job of its own (:func:`join_job`). The job's accounting holds the
CPU of every process the run ever started, ended ones included, which a walk of the process tree once a second cannot
do: a child that starts and ends between two readings is never seen, and one that ends loses what it used since the
last reading (measured on this machine: four 0.25 s children at a time hid up to 6% of the 16 threads in a second,
which would read as other load). Tests never join it; it is joined only where ``check_load`` runs as ``__main__``.

Every process the run started, except one that asked to leave the job, ends when the run ends, however it ends:
finished, stopped with Ctrl+C, or crashed. The job kills what is in it when its last handle closes
(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE), and Windows closes that handle with the run's process; the handle is not
inherited, so no child holds it open. This also clears the pytest shards an interrupted run used to leave behind.
Before, it depended on how the run was started: from a venv's ``Scripts\\python.exe`` launcher, whose own job lets
children leave it silently, they outlived the run. A child that asks to leave (CREATE_BREAKAWAY_FROM_JOB) still may
(JOB_OBJECT_LIMIT_BREAKAWAY_OK), and is then not ended with the run: ``scripts/crew/brief/land_worker.py`` asks, for
one. No other limit is set.
"""

from __future__ import annotations

import ctypes
import os
from typing import Any

KILL_ON_CLOSE = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: what is in the job ends when its last handle closes
BREAKAWAY_OK = 0x00000800  # JOB_OBJECT_LIMIT_BREAKAWAY_OK: a child that asks to leave the job still may
_JOB: list[tuple[Any, int]] = []  # (kernel32, the job's handle) once this process has joined its job
_I64, _U32, _SIZE = ctypes.c_int64, ctypes.c_uint32, ctypes.c_size_t


class _Limits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (class 9), its basic part laid out inline
    _fields_ = [
        ("PerProcessUserTimeLimit", _I64), ("PerJobUserTimeLimit", _I64), ("LimitFlags", _U32),
        ("MinimumWorkingSetSize", _SIZE), ("MaximumWorkingSetSize", _SIZE), ("ActiveProcessLimit", _U32),
        ("Affinity", _SIZE), ("PriorityClass", _U32), ("SchedulingClass", _U32), ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", _SIZE), ("JobMemoryLimit", _SIZE), ("PeakProcessMemoryUsed", _SIZE),
        ("PeakJobMemoryUsed", _SIZE),
    ]  # fmt: skip


class _Accounting(ctypes.Structure):  # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION (class 1), times in 100 ns units
    _fields_ = [
        ("TotalUserTime", _I64), ("TotalKernelTime", _I64), ("ThisPeriodTotalUserTime", _I64),
        ("ThisPeriodTotalKernelTime", _I64), ("TotalPageFaultCount", _U32), ("TotalProcesses", _U32),
        ("ActiveProcesses", _U32), ("TotalTerminatedProcesses", _U32),
    ]  # fmt: skip


def _kernel() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]  # Windows only
    handle_t, dword = ctypes.c_void_p, ctypes.c_uint32
    kernel.CreateJobObjectW.restype = kernel.GetCurrentProcess.restype = handle_t
    kernel.CreateJobObjectW.argtypes = [handle_t, ctypes.c_wchar_p]
    kernel.SetInformationJobObject.argtypes = [handle_t, ctypes.c_int, handle_t, dword]
    kernel.AssignProcessToJobObject.argtypes = [handle_t, handle_t]
    kernel.QueryInformationJobObject.argtypes = [handle_t, ctypes.c_int, handle_t, dword, handle_t]
    kernel.CloseHandle.argtypes = [handle_t]
    return kernel


def _new_job(kernel: Any) -> int | None:
    """A job whose processes end when it closes, and that a child that asks to leave may leave; nothing else is set."""
    handle = kernel.CreateJobObjectW(None, None)  # no security attributes: the handle is not inherited
    limits = _Limits(LimitFlags=KILL_ON_CLOSE | BREAKAWAY_OK)  # both are set only through the extended structure
    if handle and kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        return handle
    if handle:
        kernel.CloseHandle(handle)
    return None


def join_job() -> bool:
    """Put this process, and so every process it starts from now on, in a job of its own (:func:`_new_job`).

    True when it is in; False off Windows or when Windows refuses, and then the walk alone counts the run's own CPU and
    nothing ends the run's children with it.
    """
    if _JOB or os.name != "nt":
        return bool(_JOB)
    kernel = _kernel()
    handle = _new_job(kernel)
    if handle and kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        _JOB.append((kernel, handle))
        return True
    if handle:
        kernel.CloseHandle(handle)
    return False


def job_cpu_s() -> float | None:
    """The CPU seconds every process of this process's job has used, ended ones included; None without a job."""
    if not _JOB:
        return None
    kernel, handle = _JOB[0]
    info = _Accounting()
    if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
        return None
    return (info.TotalUserTime + info.TotalKernelTime) / 1e7
