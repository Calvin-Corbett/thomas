"""The parked autopilot checks the self-project queue after sleeping."""

from __future__ import annotations

import asyncio

import pytest

from tests.test_a_thomas_project_starts_without_chat import w  # noqa: F401
from thomas.server import autopilot_hold_tick, autopilot_park, self_project_queue_tick


def test_park_loop_runs_queue_tick_only_after_sleep(w, monkeypatch):
    async def scenario():
        ticks = []

        async def sleep(_):
            if ticks.count("queue") == 2:
                raise asyncio.CancelledError

        async def run(*a, **kw):
            ticks.append("hold")

        async def queue(*a):
            ticks.append("queue")

        monkeypatch.setattr(autopilot_park, "_sleep", sleep)
        monkeypatch.setattr(autopilot_hold_tick, "run", run)
        monkeypatch.setattr(self_project_queue_tick, "tick", queue)
        monkeypatch.setattr(autopilot_park, "rebuild", lambda *a: [])
        monkeypatch.setattr(autopilot_park, "resume_due", run)
        with pytest.raises(asyncio.CancelledError):
            await autopilot_park.park_loop({}, catalog_root=w.catalog)
        assert ticks == ["hold", "hold", "hold", "queue", "hold", "hold", "queue"]

    asyncio.run(scenario())
