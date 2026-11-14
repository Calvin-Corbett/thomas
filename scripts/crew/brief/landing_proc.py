"""Process helpers for the landing queue: start times, killing a whole tree, git lock leftovers.

Windows does not kill a process's children when it dies, and a child's own children keep pipes open after their parent
exits, so the lease kill uses a job object: every process the commit tool starts belongs to it, orphaned or not.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any

from scripts.crew.brief.landing_spawn import NO_WINDOW, hidden, popen, run  # noqa: F401 - the one place children start

try:  # optional: the POSIX start time and the "is git running" question
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

NT = os.name == "nt"
LOCK_MIN_AGE = 30.0


def start_time(pid: int | None) -> float | None:
    """The process's creation time as epoch seconds, or None when unreadable (then liveness alone is trusted)."""
    if not pid or int(pid) <= 0:
        return None
    if NT:
        return _windows_start(int(pid))
    if psutil is not None:
        try:
            return float(psutil.Process(int(pid)).create_time())
        except (psutil.Error, OSError):
            return None
    return None


def _windows_start(pid: int) -> float | None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        made, gone, kern, user = (wintypes.FILETIME() for _ in range(4))
        ok = k32.GetProcessTimes(handle, ctypes.byref(made), ctypes.byref(gone), ctypes.byref(kern), ctypes.byref(user))
        if not ok:
            return None
        return ((made.dwHighDateTime << 32) | made.dwLowDateTime) / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(handle)


def kill_tree(pid: int) -> None:
    """Best-effort: this process and everything still linked below it."""
    if NT:
        run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False, timeout=30)
        return
    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except psutil.Error:
            pass
        return
    os.kill(pid, 9)  # pragma: no cover


class JobTree:
    """Everything a child starts, orphaned or not, dies on kill() or when the process that owns the job dies (KILL_ON_JOB_CLOSE).

    ``assigned`` says whether the OS accepted the child into a job. Under a parent job that forbids nesting it may refuse
    (access denied): then ``kill`` falls back to a tree kill of what is still linked, and the caller must say so loudly:
    the lease then no longer reaches orphaned grandchildren (the ticket is marked ``unbounded``)."""

    def __init__(self, proc: subprocess.Popen[Any]):
        self.proc, self.job, self._k32, self.why_not = proc, None, None, ""
        if NT:
            self._assign_windows()
        else:
            self.why_not = ""  # POSIX: the process group is the bound

    @property
    def assigned(self) -> bool:
        return self.job is not None or not NT

    @staticmethod
    def popen_flags() -> dict[str, Any]:
        return {} if NT else {"start_new_session": True}

    def _assign_windows(self) -> None:
        class IoCounters(ctypes.Structure):
            _fields_ = [
                (n, ctypes.c_ulonglong)
                for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")
            ]

        class Basic(ctypes.Structure):
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

        class Extended(ctypes.Structure):
            _fields_ = [
                ("Basic", Basic),
                ("Io", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        job = k32.CreateJobObjectW(None, None)
        if not job:
            self.why_not = f"CreateJobObject failed ({ctypes.get_last_error()})"
            return
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: the tree dies with whoever owns the job
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.why_not = f"SetInformationJobObject failed ({ctypes.get_last_error()})"
            k32.CloseHandle(job)
            return
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(self.proc._handle))):  # type: ignore[attr-defined]
            self.why_not = (
                f"AssignProcessToJobObject refused ({ctypes.get_last_error()}; a parent job may forbid nesting)"
            )
            k32.CloseHandle(job)
            return
        self.job, self._k32 = job, k32

    def kill(self) -> None:
        if self.job is not None and self._k32 is not None:
            self._k32.TerminateJobObject(self.job, 1)
        elif not NT:
            try:
                os.killpg(self.proc.pid, 9)
            except OSError:
                pass
        else:  # no job object: kill what is still linked below the child (orphans are out of reach)
            kill_tree(self.proc.pid)

    def close(self) -> None:
        if self.job is not None and self._k32 is not None:
            self._k32.CloseHandle(self.job)
            self.job = None


def proc_cmdline(pid: int | None) -> str:
    """The command line of a process, or '' when it cannot be read."""
    if not pid or psutil is None:
        return ""
    try:
        return " ".join(psutil.Process(int(pid)).cmdline())
    except (psutil.Error, OSError):
        return ""


def _trees(root: Path) -> list[Path]:
    """This checkout and every linked worktree of the repo: their locks live in one shared git directory."""
    trees = [root.resolve()]
    done = run(
        ["git", "worktree", "list", "--porcelain"], cwd=root, capture_output=True, text=True, check=False, timeout=15
    )
    for line in done.stdout.splitlines() if done.returncode == 0 else []:
        if line.startswith("worktree "):
            trees.append(Path(line[9:]).resolve())
    return trees


def git_running(root: Path | None = None) -> bool:
    """Is a git process running that could hold this repo's locks? Without ``root`` any git counts. With it: a git whose
    working directory, ``-C`` directory or any argument is inside this checkout or a linked worktree of it, or whose
    directory cannot be read (assumed to matter)."""
    if psutil is None:  # pragma: no cover
        return True
    trees = _trees(root) if root is not None else []
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() not in ("git.exe", "git"):
                continue
            if root is None:
                return True
            try:
                places = [Path(proc.cwd()).resolve()]
                args = [str(a) for a in proc.cmdline()]
            except (psutil.Error, OSError):
                return True
            for arg in args:
                if os.sep in arg or "/" in arg:
                    try:
                        places.append(Path(arg).resolve())
                    except (OSError, ValueError):
                        continue
            if any(t == p or t in p.parents for p in places for t in trees):
                return True
    except psutil.Error:
        return True
    return False


def stale_locks(root: Path, *, now: float, min_age: float = LOCK_MIN_AGE) -> list[Path]:
    """Lock files in the repo's git dir that look abandoned (older than min_age)."""
    kw: dict[str, Any] = {"cwd": root, "capture_output": True, "text": True, "check": False, "timeout": 15}
    done = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], **kw)
    gdir = Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else root / ".git"
    head = run(["git", "symbolic-ref", "--short", "HEAD"], **kw)
    names = ["index.lock", "packed-refs.lock", "HEAD.lock"]
    if head.returncode == 0 and head.stdout.strip():
        names.append(f"refs/heads/{head.stdout.strip()}.lock")
    found = []
    for name in names:
        path = gdir / name
        try:
            if now - path.stat().st_mtime > min_age:
                found.append(path)
        except OSError:
            continue
    return found


def clean_stale_locks(
    root: Path, *, now: float | None = None, running: Callable[[], bool] | None = None
) -> tuple[list[str], list[str]]:
    """Remove abandoned git locks only when no git process runs. Returns (removed, left because git runs)."""
    locks = stale_locks(root, now=now if now is not None else time.time())
    if not locks:
        return [], []
    if (running or (lambda: git_running(root)))():
        return [], [p.name for p in locks]
    removed = []
    for path in locks:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue
    return removed, []
