"""Pause and the server's own loops: each skips a cycle while paused and works again on its next one after Resume.

Proves ``thomas.core.pause`` is honoured by ``thomas.server.autopilot_park`` (the loop that resumes parked Builds,
retries held hand-ins and starts queued Thomas projects), ``thomas.server.autopilot_restart`` (the pass that carries
Builds on after a restart), ``thomas.server.ratchet.service`` (the daily run) and
``thomas.server.consolidation_maintenance`` (the branch sweep). Each is driven through its own sleep or timer seam,
so no test waits seconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from thomas.core import pause as pause_mod


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)


def test_the_park_loop_starts_nothing_while_paused_and_carries_on_after_resume(tmp_path, monkeypatch):
    from thomas.server import autopilot_hold_tick, autopilot_park

    async def scenario() -> None:
        events: list[str] = []
        sleeps = {"n": 0}

        async def sleep(_: float) -> None:
            sleeps["n"] += 1
            if sleeps["n"] == 3:
                pause_mod.resume()  # the loop sees this on its next pass, with no restart
            if sleeps["n"] == 4:
                raise asyncio.CancelledError

        async def hold(*a: Any, **k: Any) -> None:
            events.append("hold")

        async def resume_due(*a: Any, **k: Any) -> list[str]:
            events.append("resume_due")
            return []

        async def queue(*a: Any) -> None:
            events.append("queue")

        monkeypatch.setattr(autopilot_park, "_sleep", sleep)
        monkeypatch.setattr(autopilot_park, "rebuild", lambda *a: [])
        monkeypatch.setattr(autopilot_park, "resume_due", resume_due)
        monkeypatch.setattr(autopilot_park, "_tick_self_project_queue", queue)
        monkeypatch.setattr(autopilot_hold_tick, "run", hold)
        pause_mod.pause("test")
        with pytest.raises(asyncio.CancelledError):
            await autopilot_park.park_loop({}, catalog_root=tmp_path)
        assert events == ["resume_due", "hold", "queue"]  # only the pass after Resume ran; the paused ones did nothing

    asyncio.run(scenario())


def test_a_server_that_starts_paused_does_not_retry_held_hand_ins_at_startup(tmp_path, monkeypatch):
    from thomas.server import autopilot_hold_tick, autopilot_park

    async def scenario() -> list[str]:
        events: list[str] = []

        async def sleep(_: float) -> None:
            raise asyncio.CancelledError

        async def hold(*a: Any, **k: Any) -> None:
            events.append("hold")

        monkeypatch.setattr(autopilot_park, "_sleep", sleep)
        monkeypatch.setattr(autopilot_park, "rebuild", lambda *a: [])
        monkeypatch.setattr(autopilot_hold_tick, "run", hold)
        with pytest.raises(asyncio.CancelledError):
            await autopilot_park.park_loop({}, catalog_root=tmp_path)
        return events

    pause_mod.pause("test")
    assert asyncio.run(scenario()) == []
    pause_mod.resume()
    assert asyncio.run(scenario()) == ["hold"]


def test_the_restart_pass_carries_nothing_on_while_paused_and_does_after_resume(tmp_path, monkeypatch):
    from thomas.server import autopilot_restart as restart
    from thomas.server.routes import evolve_agent_autopilot as ap

    async def scenario() -> list[str]:
        attempts: list[str] = []
        sleeps = {"n": 0}

        async def sleep(_: float) -> None:
            sleeps["n"] += 1
            if sleeps["n"] == 3:  # settle, then two paused ticks
                pause_mod.resume()
            if attempts:
                raise asyncio.CancelledError

        async def attempt(app: Any, catalog: Any, found: list[Any], *a: Any) -> None:
            attempts.append("attempt")
            found.clear()

        monkeypatch.setattr(restart, "_sleep", sleep)
        monkeypatch.setattr(restart, "survey", lambda catalog, booted: ["one interrupted run"])
        monkeypatch.setattr(restart, "_save_life", lambda catalog: None)
        monkeypatch.setattr(restart, "_cage_down", lambda: False)
        monkeypatch.setattr(restart, "_attempt", attempt)
        app = {ap.APP_PRAXIS_START_CODE_RUN: object(), ap.APP_LOCAL_PORT: 1}
        pause_mod.pause("test")
        with pytest.raises(asyncio.CancelledError):
            await restart.restart_pass(app, catalog_root=tmp_path)
        assert sleeps["n"] >= 3  # it waited out the paused ticks and kept its timer
        return attempts

    assert asyncio.run(scenario()) == ["attempt"]


def test_the_daily_ratchet_run_is_skipped_while_paused_and_runs_after_resume(tmp_path):
    from thomas.server.ratchet.service import RatchetService

    async def scenario() -> None:
        service = RatchetService(work=object(), repo=tmp_path, root=tmp_path, interval_s=0.0, first_delay_s=0.0)
        runs: list[int] = []

        async def guarded(limit: int, chat: str) -> dict[str, Any]:
            runs.append(1)
            return {"status": "ok"}

        service._guarded = guarded  # type: ignore[method-assign]
        pause_mod.pause("test")
        task = asyncio.ensure_future(service._run_daily())
        try:
            for _ in range(50):
                await asyncio.sleep(0)
            assert runs == [] and not task.done()  # idle, and the loop is still alive
            pause_mod.resume()
            for _ in range(50):
                if runs:
                    break
                await asyncio.sleep(0)
            assert runs
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_the_branch_sweep_skips_its_audit_while_paused_and_audits_after_resume(monkeypatch):
    from thomas.server import consolidation_maintenance as cm

    monkeypatch.setenv(cm.ENABLED_ENV, "1")
    audits: list[int] = []
    sleeps: list[int] = []

    async def sleep(_: float) -> None:
        sleeps.append(1)
        if len(sleeps) == 1:
            pause_mod.resume()

    def audit() -> dict[str, Any]:
        audits.append(1)
        return {}

    async def scenario() -> int:
        return await cm.consolidation_maintenance_loop(
            audit_fn=audit, sleep_fn=sleep, startup_delay_s=0, interval_s=0, max_cycles=3
        )

    pause_mod.pause("test")
    assert asyncio.run(scenario()) == 3
    assert len(audits) == 2  # the first cycle was paused
