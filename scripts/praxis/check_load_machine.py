"""How busy the machine is with work that is not the load run's own, read once a second (``check_load.py``).

Other load is the machine's busy CPU minus the CPU of this run's own process tree (``check_load`` and every process
it started, which includes each check's pytest processes), floored at 0, as a percent of the whole machine. It is a
difference of two totals and never a sum over other processes, because of what an ordinary account can read on
Windows: of another account's processes (thomas-agent's caged server, its Build team's playtests) psutil reads the
name, parent, start time, CPU times and memory, but the user name and the command line are refused (AccessDenied).

Own CPU comes from two places: the Windows job ``check_load`` joins when it runs as a script (``check_load_job``,
which holds the CPU of every process the run started, ended ones included, and ends them all with the run), and a walk
of the tree, which keeps each ended child's last reading and keeps a child whose parent ended as the run's own. The
larger of the two is used for each second, so a child that left the job is still counted when it is seen. The walk
comes first, and the job, the clock and the machine's CPU are read right after it, back to back, so however long the
walk takes never reads as other load.

Headless browser processes are counted each second, as a number only: processes of other work named like Chrome,
Edge, Chromium or Playwright's headless shell. When the command line can be read (your own account's processes), only
one with ``--headless`` or ``swiftshader`` counts, so your own browser window does not; another account's cannot be
read, so those count by name. No command line, path or user name is ever kept. A reading that fails is kept as one not
measured, said in the log, and the readings go on.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from scripts.praxis.check_load_job import job_cpu_s

OTHER_LOAD_LIMIT_PCT = 25.0  # a quarter of the machine, 4 of 16 threads: over it in any second, a check is not quiet
QUIET_NEED_S = 60.0  # --wait-quiet starts the run after this many quiet seconds in a row
SHELLS = frozenset({"chrome-headless-shell", "headless_shell"})  # a headless browser by name alone
BROWSERS = frozenset({"chrome", "msedge", "chromium", "chromium-browser"})  # headless only by its command line
HEADLESS_MARKS = ("--headless", "swiftshader")
# What an ordinary fault in a reading can be, as check_load.CHECK_ERRORS lists a check's, and SystemError, which
# psutil's compiled part can raise; psutil's own errors are caught in Sampler.read. Not Exception: the repo's
# exception gate refuses a broad catch that does not raise again.
READ_FAULTS = (
    OSError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    RuntimeError,
    ArithmeticError,
    ImportError,
    SystemError,
)
log = logging.getLogger(__name__)


class Reading(NamedTuple):
    at: float  # when it was read, as time.time()
    span_s: float  # the seconds since the reading before it; 0 for the first
    other_pct: float | None  # other load over that span, percent of the whole machine; None when not read
    browsers: int | None  # headless browser processes of other work at that moment; None when not read


def _psutil() -> Any:
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def _busy_total(times: Any) -> tuple[float, float]:
    """The busy and the total CPU seconds in psutil's system-wide ``cpu_times()``, every logical CPU summed."""
    fields = dict(times._asdict())
    for inside in ("interrupt", "dpc", "guest", "guest_nice"):  # Windows: inside system; Linux: inside user and nice
        fields.pop(inside, None)
    total = float(sum(fields.values()))
    return total - fields.get("idle", 0.0) - fields.get("iowait", 0.0), total


def _running(proc: Any, errors: tuple[type[BaseException], ...]) -> bool:
    try:
        return bool(proc.is_running())  # psutil compares the start time, so a reused process id is not taken
    except errors:
        return False


def _headless(proc: Any, stem: str, denied: type[BaseException], errors: tuple[type[BaseException], ...]) -> bool:
    if stem in SHELLS:
        return True
    try:
        line = " ".join(proc.cmdline()).lower()
    except denied:
        return True  # another account's: its command line cannot be read, so its name decides
    except errors:
        return False  # it ended
    return any(mark in line for mark in HEADLESS_MARKS)


class Sampler:
    """Each :meth:`read` gives the other load since the reading before it and the headless browser processes now."""

    def __init__(
        self,
        *,
        psutil_mod: Any = None,
        root_pid: int | None = None,
        clock: Callable[[], float] = time.time,
        job_cpu: Callable[[], float | None] = job_cpu_s,
    ) -> None:
        self._ps = _psutil() if psutil_mod is None else psutil_mod
        self.available = self._ps is not None
        self._errors: tuple[type[BaseException], ...] = (getattr(self._ps, "Error", OSError), OSError)
        self._root = os.getpid() if root_pid is None else root_pid
        self._clock, self._job_cpu = clock, job_cpu
        self._own: dict[int, Any] = {}  # this run's processes at the last walk
        self._cpu: dict[int, float] = {}  # the CPU seconds each of them had used then
        self._ended = 0.0  # what the ones that have ended had used when last read
        self._verdicts: dict[int, bool] = {}  # whether each browser-named process looked headless, read once
        self._last: tuple[float, float, float, float, float | None] | None = None
        self.own_from: str | None = None  # "job" or "process walk", once read

    def own(self) -> tuple[set[int], float]:
        """This run's processes now, and the CPU seconds they and every one of them that has ended have used."""
        alive: dict[int, Any] = {}
        try:
            root = self._ps.Process(self._root)
            alive = {root.pid: root, **{child.pid: child for child in root.children(recursive=True)}}
        except self._errors:
            pass
        for pid, proc in self._own.items():
            if pid not in alive and _running(proc, self._errors):  # its parent ended; it is still this run's
                alive[pid] = proc
        for pid in set(self._own) - set(alive):
            self._ended += self._cpu.pop(pid, 0.0)
        for pid, proc in alive.items():
            try:
                times = proc.cpu_times()
            except self._errors:
                continue  # it ended just now: its last reading stands
            self._cpu[pid] = times.user + times.system
        self._own = alive
        return set(alive), self._ended + sum(self._cpu.values())

    def _browsers(self, own: set[int]) -> int:
        verdicts: dict[int, bool] = {}
        for proc in self._ps.process_iter(["name"]):
            stem = str(proc.info.get("name") or "").lower().removesuffix(".exe")
            if proc.pid in own or (stem not in SHELLS and stem not in BROWSERS):
                continue
            known = self._verdicts.get(proc.pid)
            verdicts[proc.pid] = _headless(proc, stem, self._ps.AccessDenied, self._errors) if known is None else known
        self._verdicts = verdicts
        return sum(verdicts.values())

    def read(self) -> Reading:
        """Other load since the last reading, as a percent of the machine, and the headless browser processes now."""
        if not self.available:
            return Reading(self._clock(), 0.0, None, None)
        try:
            pids, walked = self.own()  # first: however long it takes, the four reads below are taken together
            joined = self._job_cpu()
            at = self._clock()
            busy, total = _busy_total(self._ps.cpu_times())
            browsers = self._browsers(pids)  # last: it reads every process's name
        except self._errors:
            return Reading(self._clock(), 0.0, None, None)
        self.own_from = "process walk" if joined is None else "job"
        last, self._last = self._last, (at, busy, total, walked, joined)
        if last is None:
            return Reading(at, 0.0, None, browsers)
        own = walked - last[3]
        if joined is not None and last[4] is not None:
            own = max(own, joined - last[4])  # the job also holds the children that ended between the readings
        machine = total - last[2]
        other = None if machine <= 0 else max(0.0, busy - last[1] - own) / machine * 100
        return Reading(at, round(at - last[0], 2), other, browsers)


def is_quiet(reading: Reading) -> bool:
    """Other load was read and at or under the limit, and no headless browser process of other work ran."""
    return reading.other_pct is not None and reading.other_pct <= OTHER_LOAD_LIMIT_PCT and reading.browsers == 0


def wait_allowed(seconds: float) -> bool:
    """0 turns --wait-quiet off; otherwise it is finite and at least :data:`QUIET_NEED_S`, or it could never succeed."""
    return seconds == 0 or (math.isfinite(seconds) and seconds >= QUIET_NEED_S)


def _read(sampler: Any) -> Reading:
    """One reading; one that fails is kept as not measured and said in the log, so the readings go on."""
    try:
        return sampler.read()
    except READ_FAULTS as exc:
        log.warning("a reading of the machine failed (%s: %s); it counts as not measured", type(exc).__name__, exc)
        return Reading(time.time(), 0.0, None, None)


def watch(sampler: Any, every_s: float, done: threading.Event, readings: list[Reading]) -> threading.Thread:
    """Read the machine into *readings* every *every_s* seconds until *done* is set, in a thread of its own.

    A thread apart from the free-disk readings, so a slow reading never moves them. One more reading is taken once
    *done* is set, so the last check's last second is read too.
    """

    def loop() -> None:
        while True:
            readings.append(_read(sampler))
            if done.wait(every_s):
                readings.append(_read(sampler))
                return

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def wait_quiet(
    sampler: Any,
    limit_s: float,
    *,
    every_s: float = 1.0,
    need_s: float = QUIET_NEED_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Wait until other load has stayed quiet for *need_s* seconds in a row, for at most *limit_s* seconds.

    A line is said each minute while it waits. When it gives up the run starts anyway, and what it returns says it
    never got quiet. A machine whose load cannot be read is not waited for, and ``measured`` says so.
    """
    began, quiet_s, minute, got = clock(), 0.0, 1, False
    readable = bool(getattr(sampler, "available", True))
    if readable:
        _read(sampler)  # where the first second starts
    else:
        say("other load cannot be measured here (no psutil), so the run does not wait for a quiet machine")
    while readable and clock() - began < limit_s:
        sleep(every_s)
        reading = _read(sampler)
        quiet_s = quiet_s + reading.span_s if is_quiet(reading) else 0.0
        if quiet_s >= need_s:
            got = True
            break
        if clock() - began >= 60 * minute:
            other = "-" if reading.other_pct is None else f"{reading.other_pct:.1f}%"
            processes = "-" if reading.browsers is None else reading.browsers
            say(
                f"waiting for a quiet machine: {minute} min of the {limit_s:g} s allowed; other load {other} of the"
                f" CPU, {processes} headless browser processes; quiet for {quiet_s:g} of the {need_s:g} s needed"
            )
            minute += 1
    waited_s = round(clock() - began, 1)
    return {"limit_s": limit_s, "need_s": need_s, "waited_s": waited_s, "got_quiet": got, "measured": readable}
