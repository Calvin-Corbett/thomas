"""The server says what blocked its loop, not only that it was blocked.

On 2026-11-10, with ten Builds running, the log said "Event loop was blocked for ..." 409 times in one hour, 508
seconds in all, and the server used one to two whole processors. Nothing said which code had the loop: stacks were
written only for a loop that had not run for 30 seconds, and the last of those was two days old. You said the PC's
load could not be right and asked what the server was doing with it; there was nothing to read the answer from.

Now a side thread names the function that has the main thread once the loop has gone most of a second without a
turn, adds up the seconds for each name, and the inspector gives the list at /api/inspect/server.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import FrameType

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import event_loop_blame as blame
from thomas.server.routes.cage_inspector_routes import register_cage_inspector_routes


def _frame_in(filename: str, function: str = "crunch", outer: str = "handler") -> FrameType:
    """A live frame of *function* in a file called *filename*, called from *outer* in the same file."""
    scope: dict = {"sys": sys}
    source = f"def {function}():\n    return sys._getframe()\n\ndef {outer}():\n    return {function}()\n"
    exec(compile(source, filename, "exec"), scope)  # noqa: S102 - builds a frame with a chosen file name
    return scope[outer]()


def test_it_names_the_innermost_frames_of_this_project() -> None:
    frame = _frame_in(str(Path("C:/x/thomas/server/slow_listing.py")))
    assert blame.where(frame).startswith("slow_listing.py:crunch < slow_listing.py:handler")


def test_a_block_inside_a_library_is_named_as_outside_thomas() -> None:
    frame = _frame_in(str(Path("C:/py/Lib/site-packages/somelib/thomas/io.py")))
    assert blame.where(frame).startswith("outside Thomas: io.py:crunch")
    assert blame.where(None) == "unknown"


def test_the_seconds_of_a_block_go_to_what_had_the_loop_when_it_began() -> None:
    record = blame.Blame(after_s=0.75)
    slow = _frame_in(str(Path("C:/x/thomas/server/slow_listing.py")))
    other = _frame_in(str(Path("C:/x/thomas/server/something_else.py")))

    record.look(0.2, lambda: slow)  # a short wait is nobody's fault
    record.look(0.0, lambda: slow)
    assert record.snapshot() == []

    record.look(0.8, lambda: slow)
    record.look(2.4, lambda: other)  # still the same block: the name taken when it began stands
    record.look(0.1, lambda: other)  # the loop ran again

    [row] = record.snapshot()
    assert row["where"].startswith("slow_listing.py:crunch") and row["times"] == 1 and row["seconds"] == 2.4


def test_the_list_is_the_most_seconds_first_and_cannot_grow_without_end() -> None:
    record = blame.Blame(after_s=0.5)
    for index in range(blame.KEEP + 5):
        frame = _frame_in(str(Path(f"C:/x/thomas/server/module_{index}.py")))
        record.look(1.0 + index, lambda frame=frame: frame)
        record.look(0.0, lambda frame=frame: frame)

    rows = record.snapshot(limit=500)

    assert len(rows) == blame.KEEP + 1 and any(row["where"] == "everything else" for row in rows)
    assert rows == sorted(rows, key=lambda row: -row["seconds"])


def test_the_side_thread_names_what_really_has_the_main_thread() -> None:
    record = blame.Blame(after_s=0.1)
    began: list[float] = []
    scope: dict = {"time": time}
    source = "def crunch():\n    time.sleep(0.6)\n"
    exec(compile(source, str(Path("C:/x/thomas/server/slow_listing.py")), "exec"), scope)  # noqa: S102
    stop = blame.start(lambda: time.perf_counter() - began[0] if began else 0.0, check_s=0.02, blame=record)
    try:
        began.append(time.perf_counter())
        scope["crunch"]()  # this test runs on the main thread, as the server's loop does
        began.clear()
        deadline = time.perf_counter() + 5
        while not record.snapshot() and time.perf_counter() < deadline:
            time.sleep(0.02)
    finally:
        stop.set()

    [row] = record.snapshot()
    assert threading.current_thread() is threading.main_thread()
    assert row["where"].startswith("slow_listing.py:crunch") and row["seconds"] >= 0.3


@pytest.mark.asyncio
async def test_the_inspector_gives_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    known = [{"where": "slow_listing.py:crunch", "times": 3, "seconds": 12.5}]
    monkeypatch.setattr(blame, "snapshot", lambda limit=20: known)
    app = web.Application()
    register_cage_inspector_routes(app, agent_dir=lambda: tmp_path, green_root=lambda: tmp_path)

    async with TestClient(TestServer(app)) as client:
        answer = await (await client.get("/api/inspect/server")).json()

    assert answer["ok"] is True and answer["blocked_by"] == known
    assert "max_lag_s" in answer["loop"]
