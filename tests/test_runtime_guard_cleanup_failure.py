"""A failed background guard must not interrupt the remaining app shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web

from tests.test_server_app_routes_init import _build_test_app, _Memory, _RunStore, _start_client
from thomas.server import app_runtime_guard, autopilot_park, autopilot_restart
from thomas.server.app_keys import APP_RUNTIME_GUARD_TASK


@pytest.mark.asyncio
async def test_runtime_guard_survives_worker_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = 0

    async def failing_refresh(*_args: object) -> None:
        nonlocal checks
        checks += 1
        raise TypeError("mocked process failed")

    async def next_check(_delay: float) -> None:
        if checks >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_runtime_guard, "off_loop", failing_refresh)
    with monkeypatch.context() as patches:
        patches.setattr(app_runtime_guard.asyncio, "sleep", next_check)
        with pytest.raises(asyncio.CancelledError):
            await app_runtime_guard._runtime_guard_loop(web.Application())
    assert checks == 2


@pytest.mark.asyncio
async def test_cleanup_continues_when_runtime_guard_task_died(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autopilot_park, "start_park_loop", lambda _app: None)
    monkeypatch.setattr(autopilot_restart, "start_restart_pass", lambda _app: None)
    monkeypatch.setattr(autopilot_park, "stop_park_loop", lambda _app: asyncio.sleep(0))
    monkeypatch.setattr(autopilot_restart, "stop_restart_pass", lambda _app: asyncio.sleep(0))
    run_store = _RunStore()
    memory = _Memory()
    app, _ = _build_test_app(tmp_path, monkeypatch, run_store_enabled=True, run_store=run_store, memory=memory)
    client = await _start_client(app)
    guard_task = app[APP_RUNTIME_GUARD_TASK]
    guard_task.cancel()
    await asyncio.gather(guard_task, return_exceptions=True)

    async def broken_guard() -> None:
        raise TypeError("worker process mock rejected git")

    app._state[APP_RUNTIME_GUARD_TASK] = asyncio.create_task(broken_guard())
    await asyncio.sleep(0)
    await client.close()
    assert run_store.shutdown_calls == [{"close_timeout": 5.0}]
    assert memory.closed is True
