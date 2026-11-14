"""Which other Thomas servers a starting server may stop, and which it must leave running.

On 2026-09-24 the caged server (the cage account's Thomas, port 8898) ended with
exit code 15 while five self-fix runs were working in greens. 15 is the exit code
Python's ``os.kill(pid, signal.SIGTERM)`` leaves on Windows: it calls
TerminateProcess with the signal number. ``app_lifecycle._check_single_instance``
used to stop whatever process its memory folder's ``serve.lock`` named, and any
Thomas server holding the port it wanted, without asking whose they were. A
self-fix builder that started a server of its own to look at its work could stop
the Thomas it was running inside.

The rules this module gives that check:

* A server stops only an earlier server of its own checkout: the lock must
  record the same checkout root, or the port holder's command line must show it.
  That keeps an ordinary restart working.
* Anything else holding the lock or the port is left running, and the new server
  refuses to start with a sentence saying what to do instead. A lock written
  before locks recorded their checkout proves nothing, so it is refused too.
* A server started from a green stops nothing at all. It takes a free port
  instead of the usual one and prints the address, so a builder can open it.
* The lock's PID must still be the server that wrote it. Windows hands a dead
  server's PID to the next process, so the lock records the process's start time
  too; a PID that now belongs to anything else makes the lock stale, and nothing
  is stopped.
* The caged server is never stopped by a start. Its scheduled task ends it
  before running it again, so nothing legitimate needs to, and a builder that
  runs the checkout's own ``caged_server.py`` would otherwise count as its restart.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shlex
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

# scripts/cage/shell_runner.py child_env() and check.run give every command they run
# in a green this agent id, and tests/conftest.py reads it. This guard does not: a start
# is green by where its code or folder is, never by a variable anything can drop.
from thomas.core.green_place import GREEN_AGENT_ID as GREEN_AGENT_ID
from thomas.server import green_checkout

DEFAULT_SERVE_PORT = 8899
# Distinct from a crash (1), so Task Scheduler's record of a refused start says which.
REFUSED_EXIT_CODE = 3
_VENV_DIR_NAMES = {".venv", "venv"}
# How far a lock's recorded start time may be from the OS's answer and still name
# the same process. A reused PID started after the old server exited, and that
# server lived at least as long as its imports took (about two seconds).
START_TOLERANCE_S = 1.0
CAGED_SERVER_SCRIPT = "caged_server.py"
CAGED_SERVER_TASK = "ThomasCagedServer"
# Every way a Thomas server is started: `-m thomas serve`, `-m thomas.server`
# (run-ui.ps1), the `thomas serve` console script, and the caged server.
_SERVER_ENTRY = re.compile(
    r"(?i)(?:\s-m\s+thomas(?:\.server\b|\s+serve\b)|[\\/\s\"']thomas(?:\.exe)?[\"']?\s+serve\b|caged_server\.py\b)"
)
_CAGED_ENTRY = re.compile(r"(?i)caged_server\.py\b")

# What the live process at a lock's PID is.
WRITER = "writer"  # the server that wrote the lock
STRANGER = "stranger"  # provably another process: the PID was reused
UNKNOWN = "unknown"  # the OS will not say (another account's process, no listing)


@dataclass(frozen=True)
class LockOwner:
    pid: int
    port: Any
    root: str  # "" for a lock written before locks recorded their checkout
    started_at: float | None = None  # None for a lock written before locks recorded it
    caged: bool = False  # written by the caged server


def checkout_root() -> Path:
    """The checkout this server's code was loaded from."""
    return Path(__file__).resolve().parents[2]


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def same_root(a: str | Path, b: str | Path) -> bool:
    return _norm(a) == _norm(b)


def _inside(path: str | Path, root: str | Path) -> bool:
    got, want = _norm(path), _norm(root)
    return got == want or got.startswith(want.rstrip(os.sep) + os.sep)


def started_from_green(root: Path) -> bool:
    """True when this server's code is a self-fix copy, or it was started inside one.

    Decided by where the code and the working folder are, not by the agent id the
    cage runner sets. That variable is gone the moment a command sets its own, and
    ``caged_server.py`` moves to its checkout before this runs, so a builder that
    ran the checkout's own ``caged_server.py`` looked like a restart of it. What
    keeps the caged server running then is the rule that no start stops it
    (``caged_server_refusal``).
    """
    try:
        work = (green_checkout.green_root() / "work").resolve()
        places = (root.resolve(), Path.cwd().resolve())
    except (OSError, ValueError):
        return False
    return any(_inside(place, work) for place in places)


def pid_alive(pid: int) -> bool:
    """Whether *pid* is running, failing closed when the OS will not say.

    Not ``os.kill(pid, 0)`` on Windows: signal 0 there is CTRL_C_EVENT, sent with
    GenerateConsoleCtrlEvent, and it reported success for a pid that had already
    exited (measured 2026-09-24). Same check as ``thomas/server/overlay/store.py``.
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process
    try:
        code = ctypes.c_ulong()
        return not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def process_started_at(pid: int) -> float | None:
    """When the process *pid* started (seconds since 1970), or None when the OS will not say.

    From the OS, not the clock at some later moment, so the same process always
    gives the same answer, and a PID handed to a new process gives a new one.
    """
    if pid <= 0:
        return None
    if os.name != "nt":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            ticks = int(stat[stat.rindex(")") + 2 :].split()[19])  # field 22, starttime
            boot = next(
                int(line.split()[1])
                for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                if line.startswith("btime ")
            )
            return boot + ticks / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError, StopIteration):
            return None  # no /proc (macOS) or the process is gone
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(_FileTime)] * 4
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        created, exited, kernel, user = (_FileTime() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, created, exited, kernel, user):
            return None
        ticks = (created.high << 32) | created.low  # 100 ns since 1601-01-01 UTC
        return ticks / 1e7 - 11_644_473_600.0
    finally:
        kernel32.CloseHandle(handle)


def running_as_caged_server() -> bool:
    """Whether this process was started as ``scripts/cage/caged_server.py``."""
    main_file = str(getattr(sys.modules.get("__main__"), "__file__", "") or "")
    return Path(main_file).name.lower() == CAGED_SERVER_SCRIPT


def read_lock_owner(lock_file: Path) -> LockOwner | None:
    """The server a ``serve.lock`` names, or None when it names nobody."""
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        started = data.get("started_at")
        return LockOwner(
            pid=int(data["pid"]),
            port=data.get("port", "?"),
            root=str(data.get("root") or ""),
            started_at=float(started) if isinstance(started, (int, float)) and not isinstance(started, bool) else None,
            caged=data.get("caged") is True,
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None  # missing or corrupt: the new server overwrites it


def lock_record(pid: int, host: str, port: int, root: Path) -> dict[str, Any]:
    """What a starting server writes to its ``serve.lock``."""
    return {
        "pid": pid,
        "host": host,
        "port": port,
        "root": str(root),
        "started_at": process_started_at(pid),
        "caged": running_as_caged_server(),
    }


def names_a_thomas_server(cmdline: str) -> bool:
    return bool(_SERVER_ENTRY.search(str(cmdline or "")))


def names_the_caged_server(cmdline: str) -> bool:
    return bool(_CAGED_ENTRY.search(str(cmdline or "")))


def _arguments(cmdline: str) -> list[str]:
    try:
        tokens = shlex.split(cmdline, posix=False)
    except ValueError:
        tokens = cmdline.split()
    return [token.strip("\"'") for token in tokens[1:]]


def lock_owner_identity(owner: LockOwner, started_at: float | None, cmdline: str, launcher: str) -> str:
    """WRITER, STRANGER or UNKNOWN: what the live process at the lock's PID is.

    *started_at* is the OS's start time for that PID; *cmdline* is its command
    line and *launcher* its parent's ('' when unknown). The start time decides
    when both sides have one. Otherwise the command line must be a Thomas server
    that shows the lock's checkout, itself or through the venv launcher that
    started it with the same arguments.
    """
    if owner.started_at is not None and started_at is not None:
        return WRITER if abs(owner.started_at - started_at) <= START_TOLERANCE_S else STRANGER
    cmdline = str(cmdline or "")
    if not cmdline.strip():
        return UNKNOWN
    if not names_a_thomas_server(cmdline):
        return STRANGER
    launcher = str(launcher or "")
    shows = cmdline_shows_root(cmdline, owner.root) or (
        _arguments(cmdline) == _arguments(launcher) and cmdline_shows_root(launcher, owner.root)
    )
    return WRITER if owner.root and shows else UNKNOWN


def _cmdline_paths(cmdline: str) -> list[str]:
    try:
        tokens = shlex.split(cmdline, posix=False)
    except ValueError:
        tokens = cmdline.split()
    paths: list[str] = []
    for token in tokens:
        if token.startswith("--") and "=" in token:
            token = token.split("=", 1)[1]
        token = token.strip().strip("\"'")
        if token and os.path.isabs(token):
            paths.append(token)
    return paths


def cmdline_shows_root(cmdline: str, root: str | Path) -> bool:
    """Whether a command line names a path inside *root* (its interpreter or script)."""
    return any(_inside(path, root) for path in _cmdline_paths(str(cmdline or "")))


def cmdline_checkout(cmdline: str) -> str:
    """The checkout a command line's virtual environment lives in, or ''."""
    for path in _cmdline_paths(str(cmdline or "")):
        parts = Path(path).parts
        for index, part in enumerate(parts):
            if part.lower() in _VENV_DIR_NAMES and index > 0:
                return str(Path(*parts[:index]))
    return ""


def free_port(host: str) -> int:
    family = socket.AF_INET6 if ":" in str(host) else socket.AF_INET
    bind_host = "127.0.0.1" if str(host) in {"", "0.0.0.0"} else str(host)
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind((bind_host, 0))
        return int(probe.getsockname()[1])


def green_port(host: str, port: int, listeners: set[int] | None) -> int:
    """A green's server never takes the usual port or one already in use.

    The CLI always passes a port (8899 unless told otherwise), so the usual port
    stands for "none given". A green holding it is the server a restart of the
    real Thomas would then find in its way.
    """
    if port != DEFAULT_SERVE_PORT and listeners is not None and not listeners:
        return port
    return free_port(host)


def lock_refusal(memory_root: Path, owner: LockOwner) -> str:
    other = owner.root or "a checkout it did not record"
    return (
        f"[thomas] this memory folder ({memory_root}) is used by another Thomas "
        f"({other}, PID {owner.pid}, port {owner.port}); stop that one first, or start this one "
        "with its own THOMAS_MEMORY_ROOT"
    )


def caged_server_refusal(memory_root: Path, owner: LockOwner) -> str:
    return (
        f"[thomas] this memory folder ({memory_root}) belongs to the caged server (PID {owner.pid}, "
        f"port {owner.port}), and a start never stops it; end it with "
        f"`schtasks /End /TN {CAGED_SERVER_TASK}` first, or start this one with its own THOMAS_MEMORY_ROOT"
    )


def port_refusal(host: str, port: int, other: str) -> str:
    try:
        suggestion = str(free_port(host))
    except OSError:
        suggestion = "<a free port>"
    return f"[thomas] port {port} is used by another Thomas ({other}); start this one with --port {suggestion}"


def refuse(message: str) -> NoReturn:
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(REFUSED_EXIT_CODE)
