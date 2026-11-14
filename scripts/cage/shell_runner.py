"""Runs Thomas's shell commands as the caged agent account.

Owner direction, 2026-09-22: a rule only counts if it is a wall. Thomas's
protected files are behind a card and a password, but ``shell.exec`` had no such
check: one ``git checkout`` or ``python -c`` from the shell wrote whatever the
server's own account could write. Observed live the same day, when a run put a
protected file back with a shell command.

This closes it at the only layer that can: the operating system. The server
(running as the owner) drops a command here; this runner, started by a scheduled
task **as thomas-agent**, executes it and writes back the output. thomas-agent
has read and execute on the repo but no write on Thomas's own code, so a shell
command simply cannot change it. The approved path -- the card, the PIN, then
``fs.write_protected_file`` in the server -- still can.

Deliberately standalone: no imports from ``thomas``, so it keeps working when
the agent account's access to the repo is read-only.

  python scripts/cage/shell_runner.py --cage-root C:\\ProgramData\\ThomasCage

One request is one JSON file in ``<cage>/shell/inbox``; the reply is one JSON
file in ``<cage>/shell/outbox``. Nothing in a request names a user, an account
or a privilege: it carries a command, a directory and a timeout, and the runner
executes it as itself and nothing more.

Requests are answered side by side, each on a thread of its own, up to the
machine's limit. Measured live 2026-09-23: run one after another, one self-fix
worker's two-minute test run held every other worker's ``git status`` until its
caller gave up ("the caged runner did not answer within 30s"). A request is
renamed to ``<id>.working`` before it runs, so no later poll can start it again.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import process_guard
else:  # run as a script: its own folder is first on sys.path
    import process_guard


def child_env(green: str = "") -> dict[str, str]:
    """The environment a caged command runs in.

    The agent account has no Python on its PATH -- it is a service account with
    no profile of its own to speak of, and the venv lives in the repo. Measured
    2026-09-22, the first real caged command answered `'python' is not
    recognized`, which would have made the cage a place no work could be done
    in, and a cage like that gets switched off.

    The directory comes from this process's own interpreter rather than from a
    configured path: the runner IS started with the venv's pythonw, so a caged
    `python -m pytest` gets exactly the interpreter the rest of Thomas uses, and
    nothing has to be kept in sync.

    Bytecode writing is off because most of the repo is read-only to this
    account. Python already tolerates a failed .pyc write, but silently failing
    to write hundreds of them on every run is work done to be thrown away.
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    # Output is read back as UTF-8 (run_command), so a Python child must write it.
    # Left to its locale it wrote cp1252 to the file, and the repo's own inbox check
    # printed PASS, then died on a "→" in a message and exited 1.
    env["PYTHONIOENCODING"] = "utf-8"
    # AGENTS.md has every agent start with `message.py --list`, which needs a name.
    # In green the self-development worker is that agent, and green's copy of the
    # board is its own, so it answers as one name nobody else uses.
    if green:
        env["THOMAS_AGENT_ID"] = env["AGENT_ID"] = "thomas-green"
    # Behind the fence the only way out is the proxy; pip, npm and git all read these.
    if EGRESS_PIN.is_file():
        proxy = f"http://127.0.0.1:{EGRESS_PORT}"
        env.update(HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="127.0.0.1,localhost,::1")
    scripts_dir = Path(sys.executable).resolve().parent
    if scripts_dir.is_dir():
        env["PATH"] = str(scripts_dir) + os.pathsep + env.get("PATH", "")

    # Tools that cache into the repo root cannot, because the repo root is
    # read-only here. Measured 2026-09-22: `ruff check` died with "Failed to
    # create temporary file ... .ruff_cache ... Access is denied", while pytest
    # passed 25 tests in the same cage because pytest degrades when its cache is
    # unwritable and ruff does not.
    #
    # All of this is scratch space, so pointing it at this account's own temp
    # directory costs nothing and moves no boundary. Worth remembering when the
    # cage is tightened again: what a privilege boundary usually costs is a
    # place to write scratch files, not the ability to do the work.
    cache_home = Path(tempfile.gettempdir()) / "thomas-cage"
    for name, folder in (("RUFF_CACHE_DIR", "ruff"), ("MYPY_CACHE_DIR", "mypy")):
        target = cache_home / folder
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        env[name] = str(target)
    return env


HEARTBEAT_NAME = "runner.heartbeat"
LOCK_NAME = "runner.lock"
LOG_NAME = "runner.log"
HEARTBEAT_EVERY_S = 5.0
POLL_EVERY_S = 0.25
MAX_OUTPUT_CHARS = 200_000
# The network fence (scripts/cage/egress_proxy.py; kept in step by a test, since
# this file imports nothing of Thomas's): once its pin exists, caged commands reach
# the internet only through the owner's proxy on this port.
EGRESS_PORT = 8897
EGRESS_PIN = Path(r"C:\ProgramData\ThomasPins") / "egress.allow"
# How many requests run at once: this wins, else the machine's measured limit.
WORKERS_ENV = "THOMAS_CAGE_RUNNER_WORKERS"
DEFAULT_WORKERS = 8  # nothing measured yet
MAX_WORKERS = 100  # thomas.core.machine_capacity.RUNAWAY_LIMIT
WORKING_SUFFIX = ".working"
ABANDONED = (
    "the cage runner stopped while this command was running, so it may have run in part; "
    "it was not run again. Check what it changes before running it again."
)


def channel_dirs(cage_root: Path) -> tuple[Path, Path]:
    shell = cage_root / "shell"
    return shell / "inbox", shell / "outbox"


def capacity_profile_path() -> Path:
    """Where ``thomas.core.machine_capacity`` saves this account's measured limit.

    The same data folder ``thomas.core.config.resolve_thomas_data_dir`` picks,
    worked out here because this file imports nothing of Thomas's; a test keeps
    the two in step.
    """
    base = os.environ.get("THOMAS_DATA_DIR", "").strip()
    if base:
        folder = Path(base).expanduser().resolve()
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        folder = ((Path(local).expanduser() if local else Path.home() / "AppData" / "Local") / "Thomas").resolve()
    elif sys.platform == "darwin":
        folder = (Path.home() / "Library" / "Application Support" / "Thomas").resolve()
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        folder = ((Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share") / "thomas").resolve()
    profile = re.sub(r"[^A-Za-z0-9._-]+", "-", os.environ.get("THOMAS_PROFILE", "").strip()).strip(" .-_")
    if profile and profile not in {".", ".."}:
        folder = (folder / profile).resolve()
    return folder / "machine_capacity.json"


def worker_count() -> int:
    """How many requests run at once: yours, else the machine's measured limit, else 8."""
    try:
        wanted = int(os.environ.get(WORKERS_ENV, "").strip() or 0)
    except ValueError:
        wanted = 0
    if wanted <= 0:
        try:
            saved = json.loads(capacity_profile_path().read_text(encoding="utf-8"))
            wanted = int(saved.get("limit") or 0) if isinstance(saved, dict) else 0
        except (OSError, ValueError, TypeError):
            wanted = 0
    return max(1, min(wanted or DEFAULT_WORKERS, MAX_WORKERS))


def _write_json(path: Path, payload: dict) -> None:
    """Write a reply whole: a reader must never see half a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        # Never leave a half-written .part behind for the next reader to find.
        Path(tmp).unlink(missing_ok=True)
        raise


class _Job:
    """The Windows job a command and everything it starts belong to.

    Killing cmd.exe does not kill what cmd.exe started. Measured 2026-09-22: a
    self-fix run ended while a Python process it had started kept running as this
    account with green as its folder, and green could not be removed. So each
    command starts suspended, joins a job, then runs. Every command gets a job of
    its own, ended if it times out. A green's commands also share the green's job,
    ended when the green is settled; their own jobs nest inside it. Now that a
    green's commands run side by side, one timing out must not end its siblings.
    Elsewhere this is a no-op wrapper.
    """

    def __init__(self, handle: int = 0, *, green: int = 0) -> None:
        self.handle = handle  # this command's own job
        self.green = green  # this command's handle on its green's shared job, closed with it

    def adopt(self, proc: subprocess.Popen) -> None:
        if not self.handle:
            return
        kernel32, ntdll = _winapi()
        process = int(proc._handle)  # noqa: SLF001 - Popen exposes no public process handle
        if self.green:
            kernel32.AssignProcessToJobObject(self.green, process)
        kernel32.AssignProcessToJobObject(self.handle, process)  # nests inside the green's job
        ntdll.NtResumeProcess(process)  # started suspended so nothing escapes before it joins

    def end(self, proc: subprocess.Popen) -> None:
        if self.handle:
            _winapi()[0].TerminateJobObject(self.handle, 1)
        elif os.name != "nt":
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        else:
            proc.kill()

    def release(self) -> None:
        for handle in (self.handle, self.green):
            if handle:
                _winapi()[0].CloseHandle(handle)


_GREEN_JOBS: dict[str, int] = {}
# Every request thread reads and changes the map, and end_green empties an entry.
_GREEN_JOBS_LOCK = threading.Lock()
_SUSPENDED = 0x00000004  # CREATE_SUSPENDED


def _winapi():
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("ntdll")


def _new_job(*, kill_on_close: bool) -> int:
    import ctypes
    from ctypes import wintypes

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
            ("BasicLimitInformation", Basic),
            ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = _winapi()[0]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    handle = kernel32.CreateJobObjectW(None, None) or 0
    if handle and kill_on_close:
        # If the runner itself dies, a green's processes die with it.
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
    return int(handle)


def _green_of(cwd: str | None) -> str:
    """The green a folder belongs to: <anything>/green/work/<id>[/...]."""
    if not cwd:
        return ""
    here = Path(cwd)
    for folder in (here, *here.parents):
        if folder.parent.name.lower() == "work" and folder.parent.parent.name.lower() == "green":
            return folder.name
    return ""


def _duplicate(handle: int) -> int:
    """A second handle on the same job, so the job outlives an ``end_green`` that
    closes the map's handle while a command is still starting in it."""
    import ctypes
    from ctypes import wintypes

    kernel32 = _winapi()[0]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    me = kernel32.GetCurrentProcess()
    copy = wintypes.HANDLE()
    if not handle or not kernel32.DuplicateHandle(me, handle, me, ctypes.byref(copy), 0, False, 2):  # SAME_ACCESS
        return 0
    return int(copy.value or 0)


def _job_for(cwd: str | None) -> _Job:
    if os.name != "nt":
        return _Job()
    own = _new_job(kill_on_close=False)
    green = _green_of(cwd)
    if not green or not own:
        return _Job(own)
    with _GREEN_JOBS_LOCK:
        if not _GREEN_JOBS.get(green):
            _GREEN_JOBS[green] = _new_job(kill_on_close=True)
        shared = _duplicate(_GREEN_JOBS[green])
    return _Job(own, green=shared)


def _green_pids(green: str) -> set[int]:
    """Every process a green's commands started that is still running."""
    with _GREEN_JOBS_LOCK:
        return process_guard.pids_in_job(_GREEN_JOBS.get(green, 0))


def _end_green(request: dict) -> dict:
    green = str(request.get("green") or "")
    if not green or Path(green).name != green or green in (".", ".."):
        return {"id": request.get("id"), "outcome": "invalid", "returncode": -1, "output": "invalid project id"}
    with _GREEN_JOBS_LOCK:
        handle = _GREEN_JOBS.pop(green, 0)
        if handle:
            kernel32 = _winapi()[0]
            try:
                started = process_guard.pids_in_job(handle, strict=True)
            except OSError:
                started = None
            try:
                terminated = bool(kernel32.TerminateJobObject(handle, 1))
                try:
                    remaining = process_guard.pids_in_job(handle, strict=True)
                    deadline = time.monotonic() + 1.0
                    while terminated and remaining and time.monotonic() < deadline:
                        time.sleep(0.05)
                        remaining = process_guard.pids_in_job(handle, strict=True)
                except OSError:
                    remaining = None
                left = "unknown" if remaining is None else str(sorted(remaining))
                stopped = "unknown" if started is None else str(sorted(started))
                output = f"ended green {green}; stopped process IDs: {stopped}; processes left: {left}"
                outcome, code = ("ok", 0) if terminated and started is not None and remaining == set() else ("error", 1)
            finally:
                kernel32.CloseHandle(handle)
        else:
            # No job was created for this green in this live runner. A prior runner's
            # job is killed when its last handle closes; there is nothing to stop.
            output = f"no processes recorded for green {green}; processes left: []"
            outcome, code = "ok", 0
    return {
        "id": request.get("id"),
        "outcome": outcome,
        "returncode": code,
        "output": output,
        "ran_as": os.environ.get("USERNAME") or os.environ.get("USER") or "",
    }


def run_command(request: dict) -> dict:
    """Run one request as this account and describe what happened."""
    if request.get("action") == "end_green":
        return _end_green(request)
    command = str(request.get("command") or "")
    cwd = str(request.get("cwd") or "") or None
    try:
        timeout = max(1.0, min(float(request.get("timeout_s") or 60.0), 3600.0))
    except (TypeError, ValueError):
        timeout = 60.0
    started = time.time()
    if not command.strip():
        return {"id": request.get("id"), "outcome": "invalid", "returncode": -1, "output": "empty command"}
    try:
        usable = not cwd or Path(cwd).is_dir()
    except OSError as exc:  # e.g. a folder this account may not open
        usable, cwd = False, f"{cwd} ({exc.strerror or exc})"
    if not usable:
        return {"id": request.get("id"), "outcome": "invalid", "returncode": -1, "output": f"no such directory: {cwd}"}
    green = _green_of(cwd)
    refused = process_guard.refusal(command, _green_pids(green)) if green else None
    if refused:  # a project stops only what it started (process_guard)
        return {"id": request.get("id"), "outcome": "invalid", "returncode": -1, "output": refused}

    # On Windows the whole line goes to the shell as typed. An argv list is
    # joined by subprocess.list2cmdline, which escapes inner quotes as \" --
    # an escape cmd.exe does not understand, so every command containing a
    # quote arrived mangled. The uncaged shell had the same bug and the same
    # fix; the two paths must behave identically or the cage changes what a
    # command means. POSIX needs no such care: exec takes argv directly.
    shell_cmd: list[str] | str = command if os.name == "nt" else ["bash", "-c", command]
    job = _job_for(cwd)
    try:
        # Output goes to a file, not a pipe. Anything the command leaves running
        # (start /b, a server, a hung child) inherits a pipe, and waiting for the
        # pipe to close then meant waiting for that process: the runner sat to the
        # timeout and then waited again. The command is done when its own process is.
        with tempfile.TemporaryFile() as sink:
            proc = subprocess.Popen(  # noqa: S603,S602 - the command is the owner's own request, and a shell is the point
                shell_cmd,
                shell=isinstance(shell_cmd, str),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                env=child_env(_green_of(cwd)),
                creationflags=_SUSPENDED if job.handle else 0,
                start_new_session=os.name != "nt",
            )
            job.adopt(proc)
            try:
                outcome, returncode = "ok", int(proc.wait(timeout=timeout))
            except subprocess.TimeoutExpired:
                job.end(proc)  # the command and everything it started
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                outcome, returncode = "timeout", -1
            sink.seek(0)
            output = sink.read().decode("utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        output, outcome, returncode = f"{type(exc).__name__}: {exc}", "error", -1
    finally:
        job.release()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"\n[... truncated at {MAX_OUTPUT_CHARS} characters]"
    return {
        "id": request.get("id"),
        "outcome": outcome,
        "returncode": returncode,
        "output": output,
        "ran_as": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "started_at": started,
        "finished_at": time.time(),
    }


class Workers:
    """A fixed number of threads answering requests side by side.

    A thread is reserved before a request is claimed, so when all of them are
    busy the rest wait in the inbox unclaimed -- and a runner that stops then
    still runs them after its restart instead of answering them with an error.
    """

    def __init__(self, size: int, *, on_error: Callable[[BaseException], None] | None = None) -> None:
        self.size = max(1, int(size))
        self._free = threading.BoundedSemaphore(self.size)
        self._pool = ThreadPoolExecutor(max_workers=self.size, thread_name_prefix="cage-command")
        self._on_error = on_error

    def reserve(self, *, wait: bool) -> bool:
        return self._free.acquire(blocking=wait)

    def unreserve(self) -> None:
        self._free.release()

    def start(self, work: Callable[..., None], *args: object) -> None:
        self._pool.submit(work, *args).add_done_callback(self._finished)

    def _finished(self, future: Future) -> None:
        self._free.release()
        error = None if future.cancelled() else future.exception()
        if error is not None and self._on_error is not None:
            self._on_error(error)

    def close(self, *, wait: bool) -> None:
        self._pool.shutdown(wait=wait)


# The live loop's workers, by the inbox they serve (see ``serve``).
_SERVING: dict[Path, Workers] = {}
# Windows renames through a handle opened first: two polls that both open a request
# before either renames it both succeed, the second as a rename to the name it
# already has, and both run it (measured 2026-09-23). One rename at a time closes
# that inside this process; the single-instance lock keeps any other runner out.
_CLAIMING = threading.Lock()


def _claim(request_file: Path) -> Path | None:
    """Take a request so no later poll can: one rename to its working name."""
    working = request_file.with_suffix(WORKING_SUFFIX)
    try:
        with _CLAIMING:
            os.rename(request_file, working)
    except OSError:
        return None  # its caller gave up and removed it, or it is briefly locked; look again next poll
    return working


def _answer(working: Path, outbox: Path) -> None:
    """Run one claimed request, write its reply whole, then let the request go."""
    try:
        request = json.loads(working.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        request = None
    if not isinstance(request, dict):
        request_id: object = working.stem
        reply = {"id": request_id, "outcome": "invalid", "returncode": -1, "output": "the request could not be read"}
    else:
        request_id = request.get("id")
        try:
            reply = run_command(request)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            # Answer it: a request left in the inbox after an error was retried
            # several times a second until its caller gave up (2026-09-22).
            reply = {"id": request_id, "outcome": "error", "returncode": -1, "output": f"{type(exc).__name__}: {exc}"}
    try:
        _write_json(outbox / f"{request_id}.json", reply)
    except OSError:
        pass
    working.unlink(missing_ok=True)


def serve_once(inbox: Path, outbox: Path, workers: Workers | None = None) -> int:
    """Claim the requests waiting in the inbox and start each on a thread of its own.

    Under ``serve`` this returns at once, so the next poll comes a moment later
    whatever is still running. Called on its own (``--once``, tests) it brings its
    own threads and returns when every reply is written. Returns how many it started.
    """
    pool = workers if workers is not None else _SERVING.get(inbox)
    errors: list[BaseException] = []
    own = pool is None
    if pool is None:
        pool = Workers(worker_count(), on_error=errors.append)
    started = 0
    try:
        for request_file in sorted(inbox.glob("*.json")):
            if not pool.reserve(wait=own):
                break  # every thread is busy; the rest wait, unclaimed, for the next poll
            working = _claim(request_file)
            if working is None:
                pool.unreserve()
                continue
            pool.start(_answer, working, outbox)
            started += 1
    finally:
        if own:
            pool.close(wait=True)
    if errors:
        raise errors[0]
    return started


def answer_abandoned(inbox: Path, outbox: Path) -> int:
    """Answer each request a stopped runner claimed and never finished, without running it.

    Only a request that had started is left claimed (see ``Workers``), and a
    command cut off halfway may already have changed things: running it again from
    the start is a guess about what is safe. Its caller gets an error that says so.
    """
    answered = 0
    for working in sorted(inbox.glob(f"*{WORKING_SUFFIX}")):
        try:
            request = json.loads(working.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            request = None
        request_id = (request.get("id") if isinstance(request, dict) else None) or working.stem
        try:
            reply_path = outbox / f"{request_id}.json"
            if not reply_path.exists():  # it finished just before the stop: its answer stands
                _write_json(reply_path, {"id": request_id, "outcome": "error", "returncode": -1, "output": ABANDONED})
            working.unlink(missing_ok=True)
        except OSError:
            continue  # left for the next start; a runner that cannot tidy up must still run
        answered += 1
    return answered


def take_single_instance_lock(cage_root: Path):
    """Hold the lock that says this process is THE runner, or return None.

    Three runners were found sharing one channel on 2026-09-22, left behind by
    repeated task restarts. They take turns writing the heartbeat, so the pid in
    it flaps -- confusing, but harmless. The real problem is the channel:
    ``serve_once`` reads a request, runs it, and deletes it afterwards, so two
    runners can both read the same request before either deletes it and the
    command runs twice. For anything that changes state, that is a bug with
    consequences, and it gets worse the more the cage is relied on. (A request
    is now claimed by a rename before it runs, but two processes can both win
    that rename on Windows -- see ``_CLAIMING`` -- so this lock is still what
    keeps a request to one run. Each runner also keeps its own map of green
    jobs: an ``end_green`` another runner answered would end nothing.)

    A byte-range lock, not a pid file: the lock dies with the process, so a
    runner killed mid-command leaves nothing to clean up and nothing stale to
    misread.
    """
    lock_path = cage_root / "shell" / LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 - held for the process lifetime
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def log(cage_root: Path, message: str) -> None:
    """Say what happened, where the owner can read it.

    A service that vanishes without a word is the worst thing to debug, and
    this one did exactly that three times on 2026-09-22 -- with the posture
    pinned, its silence means the shell refuses and nothing says why.
    """
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} pid={os.getpid()} {message}\n"
    try:
        path = cage_root / "shell" / LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass  # a runner that cannot log must still run


def _write_beat(heartbeat: Path) -> None:
    try:
        heartbeat.write_text(
            json.dumps({"pid": os.getpid(), "user": os.environ.get("USERNAME", ""), "at": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _beat_until(heartbeat: Path, stop: threading.Event) -> None:
    """Beat on its own thread, so a long command does not look like a death.

    The beat used to share the serve loop, so it paused for as long as a command
    took. The stale window is 20s: one 61-second test run made a perfectly
    healthy runner read as gone, and with the posture pinned `required` that
    turns every other shell call into a refusal. Measured 2026-09-22 -- and it
    fooled me into calling it dead.
    """
    while not stop.wait(HEARTBEAT_EVERY_S):
        _write_beat(heartbeat)


def serve(cage_root: Path, *, once: bool = False) -> int:
    lock = take_single_instance_lock(cage_root)
    if lock is None:
        # Exit 0, not a failure: the scheduled task restarts a failed run, and a
        # second instance failing forever would be a restart loop competing with
        # the runner that is doing the work perfectly well.
        print("another runner already holds the channel; exiting")
        log(cage_root, "exiting: another runner holds the channel")
        return 0
    inbox, outbox = channel_dirs(cage_root)
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    heartbeat = inbox.parent / HEARTBEAT_NAME
    _write_beat(heartbeat)
    abandoned = answer_abandoned(inbox, outbox)
    if abandoned:
        log(cage_root, f"answered {abandoned} request(s) a stopped runner left unfinished; none was run again")
    if once:
        serve_once(inbox, outbox)
        return 0

    def failed(exc: BaseException) -> None:
        log(cage_root, f"request failed, still serving: {type(exc).__name__}: {exc}")

    workers = Workers(worker_count(), on_error=failed)
    _SERVING[inbox] = workers
    stop = threading.Event()
    beater = threading.Thread(target=_beat_until, args=(heartbeat, stop), daemon=True, name="cage-heartbeat")
    beater.start()
    log(cage_root, f"runner started as {os.environ.get('USERNAME', '?')}, {workers.size} requests at a time")
    try:
        while True:
            try:
                serve_once(inbox, outbox)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                # One bad request must not take the runner down. It used to:
                # anything raising out of serve_once ended the process, the task
                # did not restart it (a clean exit is not a failure), and the
                # only symptom was a shell that refused everything.
                failed(exc)
            time.sleep(POLL_EVERY_S)
    finally:
        stop.set()
        _SERVING.pop(inbox, None)
        workers.close(wait=False)  # commands already running still finish and answer
        log(cage_root, "runner stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Thomas's shell commands as the caged agent account.")
    parser.add_argument("--cage-root", default=os.environ.get("THOMAS_CAGE_ROOT") or r"C:\ProgramData\ThomasCage")
    parser.add_argument("--once", action="store_true", help="answer what is waiting, then exit (for tests)")
    args = parser.parse_args(argv)
    return serve(Path(args.cage_root), once=bool(args.once))


if __name__ == "__main__":
    raise SystemExit(main())
