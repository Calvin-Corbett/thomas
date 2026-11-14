"""What every thread of this process is doing, read from inside it: a profile over some seconds, or one snapshot.

Thomas's server runs under its own Windows account, so nothing outside it can attach a profiler without an elevated
tool. On 2026-11-10 the server used one to two whole processors while Builds ran, and about a twentieth of the PC
while paused with nothing running, and there was no way to ask it why. You said: "You need to build a maintenance
tunnel into Thomas's cage."

:func:`profile` looks at every thread's stack many times a second for a few seconds and counts where each was. A
thread parked in a wait (a lock, a queue, a sleep, the loop's own poll) is counted as waiting and left out of the
list, so what remains is the code that was busy. It is a count of looks, not a measurement of processor time: a thread
shown busy may be inside a library call that is itself waiting, and the innermost frame is given so that can be told.
:func:`stacks` is one look, every thread in full. Both read only; neither keeps anything.
"""

from __future__ import annotations

import collections
import dis
import functools
import linecache
import os
import sys
import threading
import time
import traceback
from types import FrameType
from typing import Any

MAX_SECONDS = 30.0
INTERVAL_S = 0.01
_FRAMES = 3
_OURS = (f"{os.sep}thomas{os.sep}", f"{os.sep}scripts{os.sep}", "/thomas/", "/scripts/")
# The innermost frame of a thread that is parked, by file and function: such a look counts as waiting.
_WAITS = {
    ("threading.py", "wait"),
    ("threading.py", "_wait_for_tstate_lock"),
    ("queue.py", "get"),
    ("selectors.py", "select"),
    ("windows_events.py", "_poll"),
    ("windows_events.py", "select"),
    ("thread.py", "_worker"),
    ("socket.py", "accept"),
}


def _spot(frame: FrameType) -> str:
    return f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}"


@functools.lru_cache(maxsize=32)
def _blocking_offsets(code) -> frozenset[int]:
    """Bytecode offsets inside known blocking calls, not their surrounding bookkeeping."""
    instructions = list(dis.get_instructions(code))
    offsets = set()
    for instruction, following in zip(instructions, instructions[1:]):
        if instruction.opname != "CALL":
            continue
        pos = instruction.positions
        if pos.lineno is None or pos.lineno != pos.end_lineno:
            continue
        source = linecache.getline(code.co_filename, pos.lineno)[pos.col_offset : pos.end_col_offset]
        if source.startswith(("time.sleep(", "_winapi.WaitForSingleObject(", "fh.read(", "os.waitpid(")):
            offsets.update(range(instruction.offset, following.offset))
    return frozenset(offsets)


def _waiting(frame: FrameType) -> bool:
    code = frame.f_code
    if (os.path.basename(code.co_filename), code.co_name) in _WAITS:
        return True
    module = frame.f_globals.get("__name__")
    if (module == "psutil" and code.co_name == "cpu_percent") or (
        module == "subprocess" and code.co_name in {"_wait", "_communicate", "_readerthread"}
    ):
        return frame.f_lasti in _blocking_offsets(code)
    return False


def _where(frame: FrameType) -> tuple[str, str]:
    """(this project's innermost frames, the innermost frame of all), innermost first."""
    innermost = _spot(frame)
    ours: list[str] = []
    at: FrameType | None = frame
    while at is not None and len(ours) < _FRAMES:
        name = at.f_code.co_filename
        if any(mark in name for mark in _OURS) and "site-packages" not in name:
            ours.append(_spot(at))
        at = at.f_back
    return (" < ".join(ours) or "outside Thomas"), innermost


def profile(seconds: float = 5.0, *, interval_s: float = INTERVAL_S, limit: int = 40) -> dict[str, Any]:
    """Look at every other thread's stack for *seconds* and say where the busy ones were, the most looks first.

    Call it from a worker thread, never on the server's loop: it sleeps between looks."""
    seconds = min(max(0.1, float(seconds)), MAX_SECONDS)
    me = threading.get_ident()
    main = threading.main_thread().ident
    busy: collections.Counter[tuple[str, str, str]] = collections.Counter()
    looks = waiting = 0
    names: dict[int, str] = {}
    ends = time.perf_counter() + seconds
    while time.perf_counter() < ends:
        names = {thread.ident: thread.name for thread in threading.enumerate() if thread.ident is not None}
        for ident, frame in sys._current_frames().items():
            if ident == me:
                continue
            if _waiting(frame):
                waiting += 1
                continue
            ours, innermost = _where(frame)
            kind = "the loop" if ident == main else "a thread"
            busy[(kind, ours, innermost)] += 1
        looks += 1
        time.sleep(interval_s)
    rows = [
        {
            "on": kind,
            "where": ours,
            "innermost": innermost,
            "looks": count,
            # Of one processor: a thread seen busy at every look would be 100.
            "percent_of_one_processor": round(100.0 * count / looks, 1) if looks else 0.0,
        }
        for (kind, ours, innermost), count in busy.most_common(limit)
    ]
    return {
        "ok": True,
        "seconds": round(seconds, 2),
        "looks": looks,
        "threads": len(names),
        "busy_looks": sum(busy.values()),
        "waiting_looks": waiting,
        "busy": rows,
    }


def stacks(limit: int = 200) -> dict[str, Any]:
    """Every thread's whole stack now, the loop's first; a parked thread says so."""
    me = threading.get_ident()
    main = threading.main_thread().ident
    names = {thread.ident: thread.name for thread in threading.enumerate() if thread.ident is not None}
    rows = []
    for ident, frame in sys._current_frames().items():
        if ident == me:
            continue
        lines = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in traceback.extract_stack(frame)]
        rows.append(
            {
                "thread": names.get(ident, str(ident)),
                "loop": ident == main,
                "waiting": _waiting(frame),
                "stack": lines[-40:],
            }
        )
    rows.sort(key=lambda row: (not row["loop"], row["waiting"], row["thread"]))
    return {"ok": True, "threads": len(rows), "stacks": rows[:limit]}


__all__ = ["MAX_SECONDS", "profile", "stacks"]
