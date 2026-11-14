"""A machine-wide limit on how many commit gates run at the same time. Stdlib only.

Each landing runs its gates a few at a time (gate_runner). That is a win for one agent and a loss for a fleet: ten agents
each starting four gates is forty processes fighting for the same cores, and the slowest gate of every ladder (the process
scan in ``active_folder_guard``) got twice as slow under that load. Measured on the 16-core machine with ten simulated
agents, four workers each: 193 processes at the peak against 80 with one worker each, for about 12 percent more landings
per minute.

So a gate takes a SLOT before it starts and gives it back when it ends. There are a few slots for the whole machine (half
the cores, never fewer than four), so one agent on an idle machine still runs its gates side by side (two at a time by
default) and a crowd of agents shares the slots between them.

A slot is a byte-range lock on one of a few small files in a shared directory. The operating system drops the lock when the
process that holds it ends, however it ends, so a killed commit tool can never leave a slot taken and nothing needs a
"stale" rule. A gate holds exactly one slot while it runs and waits for none while holding it, so slots cannot deadlock.

The limit is about load, never about verdicts: it only decides WHEN a gate starts. If the directory cannot be used, or no
slot frees up within ``wait_seconds``, the gate runs anyway: a limiter must not stop a landing.
"""

from __future__ import annotations

import os
import random
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

SLOTS_ENV = "THOMAS_COMMIT_GATE_SLOTS"  # how many slots; 0 (or less) means no limit
DIR_ENV = "THOMAS_COMMIT_GATE_SLOT_DIR"  # where the slot files live (default: a folder in the temporary directory)
DEFAULT_WAIT_SECONDS = 120.0
POLL_SECONDS = 0.05
MAX_SLOTS = 64


def slot_count(environ: dict[str, str] | None = None, cpus: int | None = None) -> int:
    """How many gates may run at once on this machine. 0 means no limit."""
    env = os.environ if environ is None else environ
    try:
        wanted = int(str(env.get(SLOTS_ENV) or "").strip())
    except ValueError:
        return min(MAX_SLOTS, max(4, (cpus or os.cpu_count() or 4) // 2))
    return min(MAX_SLOTS, wanted) if wanted > 0 else 0


def slot_dir(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(str(env.get(DIR_ENV) or "").strip() or tempfile.gettempdir()) / "thomas-gate-slots"


def _try_lock(fd: int) -> bool:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass  # closing the file drops the lock either way


class SlotPool:
    def __init__(
        self,
        directory: Path,
        count: int,
        *,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.directory, self.count, self.wait_seconds, self.sleep, self.clock = (
            directory,
            count,
            wait_seconds,
            sleep,
            clock,
        )
        self.gave_up = 0  # times a gate ran without a slot because none freed up in time

    def _open(self, number: int) -> int | None:
        try:
            return os.open(str(self.directory / f"slot-{number:02d}.lock"), os.O_RDWR | os.O_CREAT, 0o666)
        except OSError:
            return None

    def _acquire(self) -> int | None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None  # no usable directory: no limit
        deadline = self.clock() + self.wait_seconds
        while True:
            for number in random.sample(
                range(self.count), self.count
            ):  # not always slot 0 first: spreads the contention
                fd = self._open(number)
                if fd is None:
                    continue
                if _try_lock(fd):
                    return fd
                os.close(fd)
            if self.clock() >= deadline:
                self.gave_up += 1
                return None
            self.sleep(POLL_SECONDS + random.random() * POLL_SECONDS)

    @contextmanager
    def hold(self) -> Iterator[bool]:
        """Hold one slot for the length of the ``with`` block. Yields True when it really holds one."""
        fd = self._acquire()
        try:
            yield fd is not None
        finally:
            if fd is not None:
                _unlock(fd)
                os.close(fd)


def pool(environ: dict[str, str] | None = None) -> SlotPool | None:
    """The machine's slot pool, or None when the limit is switched off."""
    count = slot_count(environ)
    return SlotPool(slot_dir(environ), count) if count > 0 else None
