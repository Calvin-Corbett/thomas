"""Run the commit tool's local gates: one at a time as before, or several at once. Stdlib only.

The verdict is the one the serial loop gave: the FIRST failing gate in registry order, with its output, or a pass.
Concurrency changes how long that takes, never what it says:

* results are kept by registry index and the failure reported is the lowest index that failed, never the first to finish;
* once a gate fails, gates after it are not started and are stopped if running, but every gate BEFORE it still finishes,
  because one of them may fail too and would have been reported first;
* gates run in three stages. Stage 0 is everything else, ``active_folder_guard`` first because it takes longest. It
  writes folder-claim state and may post coordination messages to the board, so stage 1, the gates that read the working
  tree board, starts only after stage 0 is done (as the serial order guaranteed). Stage 2 is the last inbox look and
  stays alone, last, right before the swap.
  Known difference: a gate after a refusing one may already have run its side effects (the guard's auto-claim) when the
  refusal is found. Serial never started it.
* a gate that is stopped because an earlier one failed is killed, EXCEPT the ones in NO_KILL. ``active_folder_guard``
  takes a lock file (runtime/coordination/active_folders.lock) for a few milliseconds at the end of its run, and that lock
  is only broken after 60 s. A kill that lands inside those milliseconds would leave every other agent's guard refusing for
  a minute, so the guard is left to finish and its result is thrown away. The price is that a refusal from an early gate
  waits for the guard (about 5 s) instead of 1 to 2 s. A gate that hangs past the timeout is killed whatever it is.
* every child starts with no console window and with GIT_OPTIONAL_LOCKS=0, so no two gates race over the temporary
  index's lock file when they run ``git status``.
* when several gates run at once each one first takes a machine-wide slot (gate_slots), so a crowd of agents shares the
  cores instead of each starting several gates (two per landing by default, THOMAS_COMMIT_GATE_WORKERS up to 8).

With one worker the gates run in registry order and stop at the first failure, as the old loop did. That is the same loop,
not the same tool: the batched reads, the skipped no-op gates and the rebase live elsewhere, and
THOMAS_COMMIT_LEGACY_PATH=1 turns those off too.
"""

from __future__ import annotations

import locale
import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from scripts.crew.brief import gate_slots
from scripts.crew.brief.gate_plan import (  # noqa: F401  (re-exported: callers and tests use gate_runner.<name>)
    BOARD_READERS,
    LAST,
    TYPICAL_SECONDS,
    Job,
    plan_jobs,
    stage_of,
    start_order,
)
from scripts.crew.brief.git_reads import NO_WINDOW

WORKERS_ENV = "THOMAS_COMMIT_GATE_WORKERS"
TIMEOUT_ENV = "THOMAS_COMMIT_GATE_TIMEOUT"
LEGACY_ENV = "THOMAS_COMMIT_LEGACY_PATH"  # 1: one gate at a time, nothing skipped, nothing reused, no rebase
DEFAULT_TIMEOUT = 600.0
MAX_TIMEOUT = 86400.0
MAX_WORKERS = 8
# The default per commit call. Two, not four: a review measured that four per call does not scale to a fleet (ten agents
# started forty gates at once); the machine-wide slots in gate_slots cap the total either way.
DEFAULT_MAX_WORKERS = 2
# Gates that are never killed because another gate failed first (see the module docstring).
NO_KILL = frozenset({"active_folder_guard"})
# A gate's output is read the way the serial loop read it (text mode: the locale's encoding). A child on Windows prints its
# non-ASCII characters in that encoding, and decoding them as UTF-8 turned every dash in a refusal into U+FFFD.
_OUTPUT_ENCODING = locale.getpreferredencoding(False) or "utf-8"


def legacy_requested(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(LEGACY_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def worker_count(environ: dict[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    if legacy_requested(env):
        return 1
    try:
        wanted = int(str(env.get(WORKERS_ENV) or "").strip())
    except ValueError:
        wanted = min(DEFAULT_MAX_WORKERS, max(1, (os.cpu_count() or 1) // 4))
    return max(1, min(MAX_WORKERS, wanted))


def gate_timeout(environ: dict[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    try:
        seconds = float(str(env.get(TIMEOUT_ENV) or "").strip())
    except ValueError:
        return DEFAULT_TIMEOUT
    # inf and nan are floats too, and ``communicate(timeout=inf)`` raises OverflowError instead of waiting
    return min(seconds, MAX_TIMEOUT) if math.isfinite(seconds) and seconds > 0 else DEFAULT_TIMEOUT


@dataclass
class Result:
    index: int
    name: str
    ok: bool
    output: str
    finished: float = 0.0  # monotonic clock reading
    tainted: bool = False  # the branch tip was not on the base while this gate ran
    cancelled: bool = False  # stopped or never started because an earlier gate had already failed


class Runner:
    def __init__(
        self,
        *,
        cwd: str,
        env: dict[str, str],
        workers: int = 1,
        timeout: float = DEFAULT_TIMEOUT,
        base: str | None = None,
        probe: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        slots: gate_slots.SlotPool | None = None,
    ):
        self.cwd, self.workers, self.timeout, self.base, self.probe, self.clock, self.slots = (
            cwd,
            workers,
            timeout,
            base,
            probe,
            clock,
            slots,
        )
        self.env = dict(env)
        if workers > 1:
            self.env["GIT_OPTIONAL_LOCKS"] = "0"
        self._lock = threading.Lock()
        self._running: dict[int, tuple[str, subprocess.Popen[bytes]]] = {}
        self._stopped: set[int] = set()
        self._limit: int | None = None

    # -- one gate
    def _one(self, job: Job) -> Result:
        if self.slots is None or self.workers <= 1:
            return self._run(job)
        with self.slots.hold():  # waits for a machine-wide slot; a gate that is already running is never made to wait
            if self._limit is not None and job.index > self._limit:
                # an earlier gate failed while this one waited for its slot
                return Result(job.index, job.name, False, "", cancelled=True)
            return self._run(job)

    def _run(self, job: Job) -> Result:
        tip = self.probe() if self.probe else None
        proc = subprocess.Popen(
            list(job.command),
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=NO_WINDOW,
            start_new_session=os.name != "nt",  # its own process group, so a kill reaches the gate's children too
        )
        with self._lock:
            self._running[job.index] = (job.name, proc)
        timed_out = False
        try:
            raw_out, raw_err = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            raw_out, raw_err = proc.communicate()
        finally:
            with self._lock:
                self._running.pop(job.index, None)
        text = "".join(b.decode(_OUTPUT_ENCODING, "replace") for b in (raw_out, raw_err)).replace("\r\n", "\n").strip()
        if job.index in self._stopped:
            return Result(job.index, job.name, False, text, cancelled=True)
        if timed_out:
            text = f"gate {job.name} did not finish within {self.timeout:.0f} s and was stopped\n{text}".strip()
        after = self.probe() if self.probe else None
        tainted = self.base is not None and (tip != self.base or after != self.base)
        return Result(job.index, job.name, proc.returncode == 0 and not timed_out, text, self.clock(), tainted)

    # -- serial: the old loop
    def _serial(self, jobs: Sequence[Job]) -> list[Result]:
        done: list[Result] = []
        for job in sorted(jobs, key=lambda j: j.index):
            done.append(self._one(job))
            if not done[-1].ok:
                break
        return done

    # -- pooled
    def _guarded(self, job: Job) -> Result:
        if self._limit is not None and job.index > self._limit:
            return Result(job.index, job.name, False, "", cancelled=True)
        result = self._one(job)
        if not result.ok and not result.cancelled:
            with self._lock:
                if self._limit is None or job.index < self._limit:
                    self._limit = job.index
                for index, (name, proc) in list(self._running.items()):
                    if index > self._limit:
                        self._stopped.add(index)  # its result is thrown away either way
                        if name not in NO_KILL:
                            _kill_tree(proc)
        return result

    def _pooled(self, jobs: Sequence[Job]) -> list[Result]:
        done: list[Result] = []
        for stage in (0, 1, 2):
            todo = [j for j in jobs if j.stage == stage and (self._limit is None or j.index < self._limit)]
            if not todo:
                continue
            todo = start_order(todo)
            with ThreadPoolExecutor(max_workers=min(self.workers, len(todo))) as pool:
                done.extend(pool.map(self._guarded, todo))
        return done

    def run(self, jobs: Sequence[Job]) -> list[Result]:
        """Results in registry order, for the gates that ran to the end. The first not-ok one is the verdict."""
        try:
            raw = self._serial(jobs) if self.workers <= 1 or len(jobs) <= 1 else self._pooled(jobs)
        finally:
            with self._lock:
                for index, (_name, proc) in list(
                    self._running.items()
                ):  # only on an error: the runner is being torn down
                    self._stopped.add(index)
                    _kill_tree(proc)
        return sorted((r for r in raw if not r.cancelled), key=lambda r: r.index)


def first_failure(results: Iterable[Result]) -> Result | None:
    return next((r for r in sorted(results, key=lambda r: r.index) if not r.ok), None)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """The venv launcher starts the real interpreter as a child, so killing the launcher alone leaves the gate running."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                creationflags=NO_WINDOW,
                timeout=30,
            )
        else:
            _kill_group(proc, getattr(os, "killpg", None))
    except (OSError, subprocess.SubprocessError):
        pass


def _kill_group(proc: subprocess.Popen[bytes], killpg: Callable[[int, int], None] | None) -> None:
    """Kill the gate's whole process group (POSIX). Not measured: this was written on Windows and covered by a fake only.

    The gate was started as the leader of its own process group (``start_new_session``), so its children die with it.
    Without this a child that inherited the output pipe keeps ``communicate()`` waiting after the gate itself is gone.
    """
    if killpg is None:
        proc.kill()
    else:
        killpg(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
