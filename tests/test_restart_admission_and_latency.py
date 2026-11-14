"""A restart closes check submission and promptly retries interrupted work."""

import asyncio
import threading

import pytest

from thomas.server import autopilot_restart as restart
from thomas.server.capacity_ledger import NotAdmitted
from thomas.server.precard import workers


@pytest.mark.asyncio
async def test_closed_check_admission_keeps_running_check_alive():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def check():
        entered.set()
        release.wait(5)
        finished.set()
        return "checked"

    task = asyncio.create_task(workers.off_the_loop(check))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        workers.close_admission()
        assert workers.active_calls() >= 1
        with pytest.raises(NotAdmitted, match="restarting"):
            await workers.off_the_loop(lambda: pytest.fail("late check started"))
        assert not finished.is_set()
    finally:
        release.set()
        assert await asyncio.wait_for(task, 2) == "checked"


@pytest.mark.asyncio
async def test_restart_attempts_all_six_before_sleep_and_retries_within_five_seconds(monkeypatch, tmp_path):
    from thomas.server.routes import evolve_agent_autopilot as ap

    found = [object() for _ in range(6)]
    attempts = []
    sleeps = []
    monkeypatch.setattr(restart, "survey", lambda *_: found)
    monkeypatch.setattr(restart, "_save_life", lambda *_: None)
    monkeypatch.setattr(restart, "_cage_down", lambda: False)
    monkeypatch.setattr(restart, "paused", lambda: False)

    async def attempt(_app, _catalog, items, *_args):
        attempts.append(len(items))

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError
        assert attempts == [6], "recovery slept before trying the interrupted tasks"

    monkeypatch.setattr(restart, "_attempt", attempt)
    monkeypatch.setattr(restart, "_sleep", sleep)
    app = {ap.APP_PRAXIS_START_CODE_RUN: object(), ap.APP_LOCAL_PORT: 8899}
    with pytest.raises(asyncio.CancelledError):
        await restart.restart_pass(app, catalog_root=tmp_path)
    assert attempts == [6, 6]
    assert all(seconds <= 5 for seconds in sleeps)
