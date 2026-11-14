"""What blocked the server's loop: the function that had the main thread while nothing else could run.

``event_loop_lag`` says how long the loop was blocked and never by what. On 2026-11-10, with ten Builds running, the
log held "Event loop was blocked for ..." 409 times in one hour, 508 seconds in all, the server used one to two whole
processors, and nothing anywhere said which code was responsible: the only stacks ever written are for a loop that has
not run for 30 seconds.

A side thread looks a few times a second. Once the loop has gone :data:`BLAME_AFTER_S` without a turn, it reads the
main thread's stack once and names the innermost frames of this project in it. When the loop runs again, the time it
was blocked is added to that name. :func:`snapshot` gives the names by time, for the inspector to show. It costs one
lock and one clock read per look while the loop is healthy, and it holds counts only, in memory.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from types import FrameType
from typing import Any

# A block shorter than this is not looked into: the lag watcher's own budget is half a second.
BLAME_AFTER_S = 0.75
CHECK_S = 0.25
# Names kept: enough for every real cause, small enough that a new name each time cannot grow without end.
KEEP = 60
_FRAMES = 3
_OURS = (f"{os.sep}thomas{os.sep}", f"{os.sep}scripts{os.sep}", "/thomas/", "/scripts/")


def where(frame: FrameType | None) -> str:
    """The innermost frames of this project in *frame*'s stack, innermost first: ``file.py:function < ...``.

    When none of the stack is this project's (the loop is inside a library), the innermost frames of whatever it is."""
    ours: list[str] = []
    other: list[str] = []
    while frame is not None:
        name = frame.f_code.co_filename
        spot = f"{os.path.basename(name)}:{frame.f_code.co_name}"
        if any(mark in name for mark in _OURS) and "site-packages" not in name:
            ours.append(spot)
        else:
            other.append(spot)
        frame = frame.f_back
    if ours:
        return " < ".join(ours[:_FRAMES])
    return "outside Thomas: " + " < ".join(other[:_FRAMES]) if other else "unknown"


class Blame:
    """Seconds the loop was blocked, by what had the main thread. :meth:`look` is the whole of the side thread's work."""

    def __init__(self, after_s: float = BLAME_AFTER_S) -> None:
        self.after_s = float(after_s)
        self._lock = threading.Lock()
        self._by: dict[str, list[float]] = {}
        self._current: str | None = None
        self._stalled = 0.0

    def look(self, stalled_s: float, main_frame: Callable[[], FrameType | None]) -> None:
        """One look: *stalled_s* is how long the loop has gone without a turn (0.0 when no watcher runs)."""
        if stalled_s >= self.after_s:
            if self._current is None:
                self._current = where(main_frame())
            self._stalled = stalled_s
            return
        if self._current is None:
            return
        name, seconds, self._current = self._current, self._stalled, None
        with self._lock:
            if name not in self._by and len(self._by) >= KEEP:
                name = "everything else"
            row = self._by.setdefault(name, [0, 0.0])
            row[0] += 1
            row[1] += seconds

    def snapshot(self, limit: int = 20) -> list[dict[str, Any]]:
        """What blocked the loop, the most seconds first; safe from any thread."""
        with self._lock:
            rows = [(name, int(count), float(seconds)) for name, (count, seconds) in self._by.items()]
        rows.sort(key=lambda row: -row[2])
        return [{"where": name, "times": count, "seconds": round(seconds, 1)} for name, count, seconds in rows[:limit]]


_blame = Blame()


def snapshot(limit: int = 20) -> list[dict[str, Any]]:
    """What has blocked this process's loop since it started."""
    return _blame.snapshot(limit)


def _main_frame() -> FrameType | None:
    main = threading.main_thread().ident
    return sys._current_frames().get(main) if main is not None else None


def start(since_wake: Callable[[], float], *, check_s: float = CHECK_S, blame: Blame | None = None) -> threading.Event:
    """Look from a daemon thread until the returned event is set. *since_wake* is the lag monitor's."""
    stop = threading.Event()
    target = blame if blame is not None else _blame

    def watch() -> None:
        while not stop.wait(check_s):
            target.look(since_wake(), _main_frame)

    threading.Thread(target=watch, name="event-loop-blame", daemon=True).start()
    return stop


__all__ = ["BLAME_AFTER_S", "Blame", "snapshot", "start", "where"]
