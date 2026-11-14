"""Hold the caged server, and every process it starts, under a share of this PC's processor time (2026-10-25).

You asked: "make sure thomas doesnt ever max out the pc always 90%". Making new work wait for room
(``thomas.core.machine_load``) only delays it: with ten Build teams running their own tests the PC still sat at 98%.
A Windows job object with a hard CPU rate cap holds the whole tree -- Build runners, their test runs, the check before
your card -- under ``THOMAS_MAX_LOAD_PERCENT`` (default 90; 0 turns it off) of the PC's processor time. Children stay
in the job, and the jobs Thomas makes inside it (``thomas.core.contained_process``, ``shell_runner``) are held too.
A cap that cannot be set is reported in the console log and the server starts anyway.

The limit is soft (2026-10-26, "make a soft limiter ... average utilization over 5 mins is 90% then start reducing
stuff the focus again is Thomas getting more done"). Thomas starts with the whole PC. Every ``FOLLOW_S`` seconds the
whole PC's load is read; only when its average over ``WINDOW_S`` (5 minutes) is at or over the limit is Thomas's share
cut, ``STEP_POINTS`` at a time and at most once a ``SETTLE_S``, never under ``FLOOR_PERCENT``; once the average is
``EASE_POINTS`` under the limit it is given back the same way, up to all of it. (Task Scheduler already runs the tree
below normal priority, so your apps win whenever they compete.)
"""

from __future__ import annotations

import collections
import ctypes
import os
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

LIMIT_ENV = "THOMAS_MAX_LOAD_PERCENT"
CAPPED_ENV = "THOMAS_CPU_CAPPED"  # keep in lockstep with thomas.core.machine_load.CAPPED_ENV
DEFAULT_PERCENT = 90.0
FLOOR_PERCENT = 30.0  # the least Thomas keeps while the PC stays busy
FOLLOW_S = 10.0
WINDOW_S = 300.0  # the average the limit is judged on
SETTLE_S = 60.0  # at most one move a minute, so each move is seen before the next
STEP_POINTS = 10.0
EASE_POINTS = 5.0  # given back only once the average is this far under the limit
_BASIC_ACCOUNTING = 1  # JobObjectBasicAccountingInformation
_CPU_RATE_INFORMATION = 15  # JobObjectCpuRateControlInformation
_ENABLE, _HARD_CAP = 0x1, 0x4  # JOB_OBJECT_CPU_RATE_CONTROL_ENABLE, JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
_job: Any = None  # held for the life of the process


class CpuRate(ctypes.Structure):
    """JOBOBJECT_CPU_RATE_CONTROL_INFORMATION: CpuRate is processor cycles per 10,000, across every processor."""

    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


class Accounting(ctypes.Structure):
    """JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: processor time of every process the job held, in 100 ns units."""

    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def next_share(share: float, average: float, limit: float, floor: float = FLOOR_PERCENT) -> float:
    """Thomas's next share: a step down while the PC's average is at or over *limit*, a step back up once it is
    ``EASE_POINTS`` under it, otherwise unchanged; between *floor* and 100."""
    if average >= limit:
        return max(min(floor, limit), share - STEP_POINTS)
    if average <= limit - EASE_POINTS:
        return min(100.0, share + STEP_POINTS)
    return share


def _ticks(value: Any) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


class Follower:
    """Every FOLLOW_S, reads the PC's load; moves the job's rate by :func:`next_share` of its WINDOW_S average."""

    def __init__(self, kernel: Any, job: Any, limit: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.kernel, self.job, self.limit, self.clock = kernel, job, limit, clock
        self.share = 100.0  # the whole PC until its average says otherwise
        self.cpus = os.cpu_count() or 1
        self.last: tuple[float, int, int, int] | None = None
        self.loads: collections.deque[tuple[float, float]] = collections.deque()  # (when, the PC's load %)
        self.moved = float("-inf")

    def _read(self) -> tuple[float, int, int, int] | None:
        """(when, the job's processor time, the PC's busy time, the PC's whole time), times in 100 ns."""
        spent = Accounting()
        if not self.kernel.QueryInformationJobObject(
            self.job, _BASIC_ACCOUNTING, ctypes.byref(spent), ctypes.sizeof(spent), None
        ):
            return None
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not self.kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        whole = _ticks(kernel) + _ticks(user)  # kernel time includes the idle time
        return self.clock(), spent.TotalUserTime + spent.TotalKernelTime, whole - _ticks(idle), whole

    def step(self) -> float | None:
        """One reading; the share it holds, or None while it has no interval to measure yet."""
        now, last = self._read(), self.last
        self.last = now
        if now is None or last is None or now[3] <= last[3] or now[0] <= last[0]:
            return None
        self.loads.append((now[0], 100.0 * (now[2] - last[2]) / (now[3] - last[3])))
        while self.loads and self.loads[0][0] < now[0] - WINDOW_S:
            self.loads.popleft()
        if now[0] - self.loads[0][0] < WINDOW_S - 2 * FOLLOW_S or now[0] - self.moved < SETTLE_S:
            return self.share  # a full window, and a minute since the last move, before anything moves
        average = sum(load for _, load in self.loads) / len(self.loads)
        share = next_share(self.share, average, self.limit)
        if share != self.share:
            rate = CpuRate(_ENABLE | _HARD_CAP, int(round(share * 100)))
            if self.kernel.SetInformationJobObject(
                self.job, _CPU_RATE_INFORMATION, ctypes.byref(rate), ctypes.sizeof(rate)
            ):
                self.share, self.moved = share, now[0]
        return self.share

    def run(self) -> None:
        while True:
            try:
                self.step()
            except (OSError, ValueError, ArithmeticError):
                self.last = None  # start the interval again
            time.sleep(FOLLOW_S)


def percent() -> float:
    try:
        value = float(os.environ.get(LIMIT_ENV) or DEFAULT_PERCENT)
    except ValueError:
        return DEFAULT_PERCENT
    return value if 0 <= value <= 100 else DEFAULT_PERCENT


def _kernel32() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    ]  # fmt: skip
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.GetSystemTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel.GetSystemTimes.restype = wintypes.BOOL
    return kernel


def cap_this_process_tree(kernel: Any = None, *, follow: bool = True) -> str:
    """Put this process, and so everything it starts, in a job capped at :func:`percent`, and (with *follow*) keep
    the cap at what the rest of the PC leaves; say what happened."""
    global _job
    share = percent()
    if share <= 0 or share >= 100:
        return f"no CPU cap ({LIMIT_ENV}={share:g})"
    if kernel is None:
        if os.name != "nt":
            return "no CPU cap (not Windows)"
        if os.environ.get("PYTEST_CURRENT_TEST"):  # a test that runs caged_server.main must not cap the test run
            return "no CPU cap (under pytest)"
        kernel = _kernel32()
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return f"no CPU cap: a job could not be made (error {ctypes.get_last_error()})"
    rate = CpuRate(_ENABLE | _HARD_CAP, 10_000)  # all of it: the follower cuts it only on a busy 5-minute average
    if not kernel.SetInformationJobObject(job, _CPU_RATE_INFORMATION, ctypes.byref(rate), ctypes.sizeof(rate)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        return f"no CPU cap: the job refused the rate (error {error})"
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        return f"no CPU cap: this process could not join the job (error {error})"
    _job = job
    os.environ[CAPPED_ENV] = f"{share:g}"  # inherited by every child: their CPU waits for room stand down
    if follow:
        threading.Thread(target=Follower(kernel, job, share).run, name="cpu-cap-follower", daemon=True).start()
    return (
        f"CPU soft limit: this server and everything it starts are slowed only while this PC averages {share:g}% or"
        f" more over {WINDOW_S / 60:g} minutes, {STEP_POINTS:g} points a minute, never under {FLOOR_PERCENT:g}%"
    )


__all__ = [
    "DEFAULT_PERCENT",
    "FLOOR_PERCENT",
    "LIMIT_ENV",
    "Accounting",
    "CpuRate",
    "Follower",
    "cap_this_process_tree",
    "next_share",
    "percent",
]
