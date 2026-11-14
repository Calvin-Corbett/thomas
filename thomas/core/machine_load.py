"""Keep this PC under 90%: new work waits while CPU or memory is above the limit.

On 2026-10-25 the PC sat at 100% CPU on all 16 cores, with 15 to 26 threads waiting, and nothing Thomas was building
finished for 17 hours. You asked: "make sure thomas doesnt ever max out the pc always 90%". This reads the whole
machine's CPU and memory (``psutil``) a few times a minute and averages the CPU over the last :data:`WINDOW_S`
seconds, so one busy second does not hold anything. :func:`wait_for_room` (threads) and :func:`await_room` (the
server's event loop) make NEW work wait -- a test run, a check's test batch, a Build run -- and never stop or kill
work that is already running.

A wait ends after its own limit even when the PC is still busy: load from outside Thomas (an antivirus scan, the search
indexer, a game) must not stop him for good. ``THOMAS_MAX_LOAD_PERCENT`` sets the limit (default 90; 0 turns it off).
Never raises: a reading that cannot be taken is "room", not a stop.

Test runs do not wait that way: they wait their turn in one line for the whole account (:class:`Line`), for as long as
it takes, because a test run started on a PC with no room is slower for every other one and ends at its own time limit
with nothing learned.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIMIT_ENV = "THOMAS_MAX_LOAD_PERCENT"
CAPPED_ENV = "THOMAS_CPU_CAPPED"  # set by scripts/cage/cpu_cap once the hard cap holds this process tree
DEFAULT_LIMIT = 90.0
WINDOW_S = 20.0
SAMPLE_S = 2.0
CHECK_S = 5.0


@dataclass(frozen=True)
class Reading:
    cpu: float  # the average over the last WINDOW_S seconds, 0-100
    memory: float  # the latest, 0-100
    samples: int


def limit() -> float:
    """The limit in percent, or 0 when it is off. A value that is not a number is the default.

    Off under pytest unless a test sets ``THOMAS_MAX_LOAD_PERCENT``: the suite runs these paths on a machine that is
    busy running it, and every shard, test run and Build start in it would wait out its limit."""
    raw = str(os.environ.get(LIMIT_ENV) or "").strip()
    if not raw:
        return 0.0 if os.environ.get("PYTEST_CURRENT_TEST") else DEFAULT_LIMIT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LIMIT
    return min(max(value, 0.0), 100.0)


class _Sampler:
    """One background thread per process, started on first use, that keeps the last WINDOW_S seconds of readings."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: collections.deque[tuple[float, float, float]] = collections.deque()
        self._thread: threading.Thread | None = None

    def _read(self, interval: float | None) -> tuple[float, float] | None:
        try:
            import psutil

            return float(psutil.cpu_percent(interval=interval)), float(psutil.virtual_memory().percent)
        except (ImportError, OSError, RuntimeError, ValueError, AttributeError):
            return None

    def _keep(self, cpu: float, memory: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._samples.append((now, cpu, memory))
            while self._samples and now - self._samples[0][0] > WINDOW_S:
                self._samples.popleft()

    def _run(self) -> None:
        while True:
            got = self._read(SAMPLE_S)  # blocks SAMPLE_S and measures over it
            if got is not None:
                self._keep(*got)
            else:
                time.sleep(SAMPLE_S)

    def latest(self) -> Reading | None:
        """What is known now, without waiting for a first measurement (None before it): for the step log."""
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="machine-load", daemon=True)
                self._thread.start()
            if not self._samples:
                return None
            cpus = [cpu for _t, cpu, _m in self._samples]
            return Reading(sum(cpus) / len(cpus), self._samples[-1][2], len(cpus))

    def reading(self) -> Reading | None:
        with self._lock:
            started = self._thread is not None
            if not started:
                self._thread = threading.Thread(target=self._run, name="machine-load", daemon=True)
                self._thread.start()
            empty = not self._samples
        if empty:  # a process's first look: measure one second now rather than answer with nothing
            got = self._read(1.0)
            if got is None:
                return None
            self._keep(*got)
        with self._lock:
            cpus = [cpu for _t, cpu, _m in self._samples]
            return Reading(sum(cpus) / len(cpus), self._samples[-1][2], len(cpus))


_sampler = _Sampler()


def reading() -> Reading | None:
    """This PC's load now, or None when it cannot be read."""
    return _sampler.reading()


def latest() -> Reading | None:
    """This PC's load as last measured, never waiting for a measurement."""
    return _sampler.latest()


def _note_wait(label: str, waited: float, why: str) -> None:
    """A wait that happened goes in the step log, with what waited and why."""
    if why:
        from thomas.core import step_log

        step_log.record("load_wait", seconds=waited, where=label or "unnamed", why=why)


def over_limit(now: Reading | None = None) -> str:
    """Why new work should wait ("" when there is room): CPU or memory at or above the limit."""
    cap = limit()
    if cap <= 0:
        return ""
    now = now if now is not None else reading()
    if now is None:
        return ""
    # Under the caged server's hard CPU cap (scripts/cage/cpu_cap) Thomas cannot pass the limit, so a CPU wait would
    # only make him give way to other programs and then run anyway (~90 s per test run, 2026-10-25); memory still waits.
    if now.cpu >= cap and not os.environ.get(CAPPED_ENV):
        return f"this PC's CPU is at {now.cpu:.0f}% (the limit is {cap:.0f}%)"
    if now.memory >= cap:
        return f"this PC's memory is at {now.memory:.0f}% (the limit is {cap:.0f}%)"
    return ""


def wait_for_room(
    *,
    max_wait_s: float,
    label: str = "",
    read: Callable[[], Reading | None] = reading,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[float, str]:
    """Wait while the PC is over the limit, at most *max_wait_s*: (seconds waited, why it waited, "" if it did not).
    *label* names what waited in the step log."""
    started = clock()
    first = ""
    while True:
        why = over_limit(read())
        left = max_wait_s - (clock() - started)
        if not why or left <= 0:
            waited = clock() - started
            _note_wait(label, waited, first or why if left <= 0 else first)
            return waited, first or (why if left <= 0 else "")
        first = first or why
        sleep(min(CHECK_S, left))


async def await_room(
    *,
    max_wait_s: float,
    label: str = "",
    read: Callable[[], Reading | None] = reading,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[float, str]:
    """:func:`wait_for_room` for the event loop: the reading is taken off the loop, the wait is ``asyncio.sleep``."""
    started = clock()
    first = ""
    while True:
        why = over_limit(await asyncio.to_thread(read))
        left = max_wait_s - (clock() - started)
        if not why or left <= 0:
            waited = clock() - started
            _note_wait(label, waited, first or why if left <= 0 else first)
            return waited, first or (why if left <= 0 else "")
        first = first or why
        await asyncio.sleep(min(CHECK_S, left))


LINE_FILE = "test_line.sqlite3"
LINE_BEAT_S = 10.0  # a waiting run writes that it is still there this often
LINE_GONE_S = 60.0  # a waiting run that has not written so for this long has left the line
LINE_RUN_MAX_S = 2400.0  # held longer than any run may last (a check shard: 1800 s) is a place not given back
log = logging.getLogger(__name__)


def _born(pid: int) -> float | None:
    """When the process with this id began, which with the id names it; None when it is gone or cannot be read."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.Error, OSError):
        return None


def _own_job() -> tuple[float, int] | None:
    """(the share of this PC the Windows job this process is in may use, in percent; the processor time the job has
    used, in 100 ns), or None when this process is in no job or in one with no hard cap on its rate."""
    import ctypes
    from ctypes import wintypes

    query = ctypes.WinDLL("kernel32", use_last_error=True).QueryInformationJobObject
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    query.restype = wintypes.BOOL
    rate = (wintypes.DWORD * 2)()  # JOBOBJECT_CPU_RATE_CONTROL_INFORMATION: flags, then cycles per 10,000
    if not query(None, 15, rate, ctypes.sizeof(rate), None) or rate[0] & 0x5 != 0x5:  # enabled, and a hard cap
        return None
    spent = (ctypes.c_int64 * 6)()  # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: user, kernel time first
    if not query(None, 1, spent, ctypes.sizeof(spent), None):
        return None
    return rate[1] / 100.0, int(spent[0] + spent[1])


class JobMeter:
    """What the CPU cap on the caged server lets its tree use, and what the tree used: (share, used), in percent.

    The cap (scripts/cage/cpu_cap.py) is a hard CPU rate on the Windows job that holds the caged server and every
    process it starts, so a Build agent asks its own job. That needs nothing from the cap's follower, whose thread
    keeps the code it started with until the whole cage process starts again. None when this process is under no cap.
    """

    def __init__(
        self,
        query: Callable[[], tuple[float, int] | None] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        cpus: int | None = None,
    ) -> None:
        self._query, self._clock = query, clock
        self._cpus = max(1, int(cpus or os.cpu_count() or 1))
        self._samples: collections.deque[tuple[float, int]] = collections.deque()

    def read(self) -> tuple[float, float] | None:
        query = self._query
        if query is None:
            if os.name != "nt" or not os.environ.get(CAPPED_ENV):
                return None
            query = _own_job
        try:
            got = query()
        except (OSError, ValueError, AttributeError, TypeError):
            return None
        if got is None:
            return None
        share, ticks = got
        now = self._clock()
        self._samples.append((now, ticks))
        while len(self._samples) > 1 and now - self._samples[0][0] > WINDOW_S:
            self._samples.popleft()
        then, before = self._samples[0]
        if now - then < 1.0:
            return share, share  # nothing measured yet: as if the tree used all it may
        return share, max(0.0, (ticks - before) * 100.0 / ((now - then) * 1e7 * self._cpus))


class Line:
    """One line, for every Build under this account, of test runs waiting for this PC to have room.

    On 2026-11-13 ten Builds ran thirteen test runs at once on a PC already at 90%. 48 runs were killed at
    check.run's 9-minute limit that day (7.2 hours of them), a check before a card waited 92 minutes for tests that
    never finished, and nothing landed. A test run now takes a ticket here and starts when its turn comes: first
    come, first served; never more at once than the limit leaves threads for (``most``); and while the PC is at its
    limit, or the runs that just started would take it there, no more than ``least``, which may always run.

    Room is counted in whole runs from the front of the line, so a place is offered to a run only when every run
    ahead of it fits too. Under the CPU cap on the caged server the reading of the whole PC says little: the cap
    holds it under the limit while the tree Thomas runs has no processor time to give. There the room is also what
    the cap leaves of the share of the cage (:class:`JobMeter`). Every age is read from the monotonic clock, one
    count for every process of a boot, so setting the wall clock gives up no place.

    Kept in one SQLite file in Thomas's data folder, which every Build agent of the account opens. A ticket is given
    up by the next run that looks when its process has died, when it has held its place past :data:`LINE_RUN_MAX_S`,
    or when its waiting run has stopped asking: nothing here can hold the line for good. Raises ``sqlite3.Error`` or
    ``OSError`` when the file cannot be used; the caller then runs its tests without a place rather than not at all.
    """

    def __init__(
        self,
        path: Path,
        *,
        cpus: int | None = None,
        cap: Callable[[], float] = limit,
        read: Callable[[], Reading | None] = reading,
        clock: Callable[[], float] = time.monotonic,
        born: Callable[[int], float | None] = _born,
        held: Callable[[], tuple[float, float] | None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._cpus = max(1, int(cpus or os.cpu_count() or 1))
        self._cap, self._read, self._clock, self._born, self._held = cap, read, clock, born, held
        if held is None:
            self._held = JobMeter().read
        began = born(os.getpid())
        if began is None:
            raise OSError("the line of test runs could not tell this process from another")
        self._me = (os.getpid(), began)
        self._mine: dict[int, tuple[str, float, float]] = {}  # ticket -> its label, when it joined, when it last wrote
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db().close()

    def _db(self) -> sqlite3.Connection:
        """The line's file, opened; its table is made here, so a file that was removed is a line again."""
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA busy_timeout=30000")
        db.execute(
            "CREATE TABLE IF NOT EXISTS line (ticket INTEGER PRIMARY KEY AUTOINCREMENT, pid INTEGER NOT NULL, "
            "born REAL NOT NULL, label TEXT NOT NULL, joined REAL NOT NULL, seen REAL NOT NULL, started REAL)"
        )
        return db

    def places(self) -> tuple[int, int]:
        """The most test runs at once, and the least that may always run however busy the PC is."""
        cap = self._cap()
        most = max(1, int(self._cpus * cap / 100)) if cap > 0 else self._cpus
        return most, min(most, max(1, self._cpus // 8))

    def join(self, label: str) -> int:
        """Take a ticket at the end of the line."""
        now, joined = self._clock(), time.time()  # the wall time is only for a page that shows the line
        with closing(self._db()) as db:
            ticket = int(
                db.execute(
                    "INSERT INTO line (pid, born, label, joined, seen) VALUES (?, ?, ?, ?, ?)",
                    (*self._me, str(label), joined, now),
                ).lastrowid
            )
        self._mine[ticket] = (str(label), joined, now)
        return ticket

    def look(self, ticket: int) -> tuple[bool, int]:
        """Whether this run may start now (its place is then taken), and how many waiting runs are ahead of it."""
        now = self._clock()
        with closing(self._db()) as db:
            start, ahead, write = self._turn(db, ticket, now, apply=False)
            if write:  # the place is taken, and tickets given up, with the file held: no two runs take one place
                done = False
                db.execute("BEGIN IMMEDIATE")
                try:
                    start, ahead, _ = self._turn(db, ticket, now, apply=True)
                    db.execute("COMMIT")
                    done = True
                finally:
                    if not done:
                        db.execute("ROLLBACK")
        return start, ahead

    def leave(self, ticket: int) -> None:
        """Give the ticket back: its run has ended, or is no longer wanted."""
        self._mine.pop(ticket, None)
        with closing(self._db()) as db:
            db.execute("DELETE FROM line WHERE ticket=?", (ticket,))

    def rows(self) -> list[dict[str, Any]]:
        """Every ticket in the line, first come first: for a page that shows what is waiting."""
        with closing(self._db()) as db:
            found = db.execute("SELECT ticket, pid, label, joined, started FROM line ORDER BY ticket").fetchall()
        return [
            {"ticket": t, "pid": pid, "label": label, "joined": joined, "state": "waiting" if s is None else "running"}
            for t, pid, label, joined, s in found
        ]

    def _turn(self, db: sqlite3.Connection, ticket: int, now: float, *, apply: bool) -> tuple[bool, int, bool]:
        """(may start, waiting runs ahead, something is to be written); with *apply*, it is written."""
        rows = db.execute("SELECT ticket, pid, born, seen, started FROM line ORDER BY ticket").fetchall()
        living: dict[tuple[int, float], bool] = {}

        def gone(row: tuple[Any, ...]) -> bool:
            number, pid, born, seen, started = row
            owner = (int(pid), float(born))
            if owner not in living:
                at = None if owner == self._me else self._born(owner[0])
                living[owner] = owner == self._me or (at is not None and abs(at - owner[1]) < 0.01)
            if not living[owner]:
                return True
            if started is not None:
                return now - started > LINE_RUN_MAX_S
            return number != ticket and now - seen > LINE_GONE_S

        left = [row[0] for row in rows if gone(row)]
        here = [row for row in rows if row[0] not in left]
        running = [row[4] for row in here if row[4] is not None]
        waiting = [row[0] for row in here if row[4] is None]
        mine = next((row for row in here if row[0] == ticket), None)
        if mine is not None and mine[4] is not None:
            return True, 0, False  # already started
        label, joined, wrote = self._mine.get(ticket, ("test run", time.time(), float("-inf")))
        if mine is None:  # given up while this process could not ask (the PC slept): it takes its old place again
            if not apply:
                return False, len(waiting), True
            db.execute(
                "INSERT OR IGNORE INTO line (ticket, pid, born, label, joined, seen) VALUES (?, ?, ?, ?, ?, ?)",
                (ticket, *self._me, label, joined, now),
            )
            waiting = sorted([*waiting, ticket])
        ahead = waiting.index(ticket)
        start = ahead < self._room(running, now)
        if not apply:
            return start, ahead, bool(start or left or now - wrote >= LINE_BEAT_S)
        db.executemany("DELETE FROM line WHERE ticket=?", [(number,) for number in left])
        db.execute("UPDATE line SET seen=?, started=? WHERE ticket=?", (now, now if start else None, ticket))
        self._mine[ticket] = (label, joined, now)
        return start, ahead, False

    def _room(self, running: list[float], now: float) -> int:
        """How many of the waiting runs may start now, counted from the front of the line."""
        most, least = self.places()
        cap, read, held = self._cap(), self._read(), self._held()
        fits: float | None = None  # the runs the measured processor time leaves room for, each one thread
        if cap > 0 and read is not None:
            fits = 0.0 if read.memory >= cap else (cap - read.cpu) * self._cpus / 100.0
        if held is not None:
            share, used = held
            most = max(least, min(most, int(self._cpus * share / 100.0)))
            inside = (share - used) * self._cpus / 100.0
            fits = inside if fits is None else min(fits, inside)
        room = most - len(running)
        if fits is not None:
            # A run that started inside the measuring window is not in any average yet: it is taken off the room.
            fresh = sum(1 for started in running if 0 <= now - started < WINDOW_S)
            room = min(room, max(int(fits) - fresh, least - len(running)))
        return room


_line: Line | None = None
_line_lock = threading.Lock()


def line() -> Line | None:
    """This account's line for test runs; None when there is none to wait in. Never raises.

    None when the limit is off (0; and under pytest unless a test sets it, as for :func:`limit`), and when the line's
    file cannot be opened: tests then run at once, as they did before there was a line.
    """
    global _line
    if limit() <= 0:
        return None
    with _line_lock:
        if _line is None:
            try:
                from thomas.core.config import resolve_thomas_data_dir

                _line = Line(Path(resolve_thomas_data_dir()) / LINE_FILE)
            except (ImportError, OSError, sqlite3.Error, ValueError) as exc:
                log.warning("the line of test runs could not be opened (%s: %s)", type(exc).__name__, exc)
                return None
        return _line


__all__ = [
    "CAPPED_ENV",
    "DEFAULT_LIMIT",
    "JobMeter",
    "LIMIT_ENV",
    "LINE_FILE",
    "Line",
    "Reading",
    "await_room",
    "latest",
    "limit",
    "line",
    "over_limit",
    "reading",
    "wait_for_room",
]
