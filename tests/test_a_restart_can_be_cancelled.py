"""A restart that waits for checks must be cancellable: it held new Build starts closed for an hour, and Thomas looked frozen."""

import asyncio

import pytest

from thomas.server import landed_code_reload as reload
from thomas.server import owner_restart as restart
from thomas.server.app_keys import APP_SHUTDOWN_EVENT
from thomas.server.precard import workers


@pytest.mark.asyncio
async def test_cancel_reopens_admission_and_clears_the_drain(monkeypatch):
    app = {APP_SHUTDOWN_EVENT: asyncio.Event()}
    resumed = []

    async def finish(_app):
        return None

    async def resume(_app):
        resumed.append(True)

    async def waiting(_app):
        return ()

    monkeypatch.setattr(restart.landed_code_resume, "finish_drain", finish)
    monkeypatch.setattr(restart.landed_code_resume, "resume", resume)
    monkeypatch.setattr(reload, "waiting_work", waiting)
    monkeypatch.setattr(reload, "active_work", lambda _app: ())
    monkeypatch.setattr(reload, "_signal_runs", lambda *_args: None)
    monkeypatch.setattr(restart, "POLL_S", 0.001)
    rows = [{"id": "check-1", "kind": "check", "state": "admitted"}]
    monkeypatch.setattr(restart.capacity_ledger, "rows", lambda: list(rows))

    restart.request_restart(app)
    task = app[restart.APP_OWNER_RESTART_TASK]
    for _ in range(100):
        if restart.status(app)["checks_running"] == 1:
            break
        await asyncio.sleep(0.005)
    assert restart.status(app)["restarting"] is True
    assert asyncio.get_running_loop() in workers._closed_admission

    after = await restart.cancel_restart(app)
    await asyncio.gather(task, return_exceptions=True)

    assert after["restarting"] is False
    assert asyncio.get_running_loop() not in workers._closed_admission
    assert reload.APP_LANDED_CODE_DRAIN not in app
    assert resumed
    assert not app[APP_SHUTDOWN_EVENT].is_set()
    assert len(rows) == 1  # running checks are never touched


@pytest.mark.asyncio
async def test_cancel_with_no_restart_is_a_no_op():
    app = {APP_SHUTDOWN_EVENT: asyncio.Event()}
    assert (await restart.cancel_restart(app))["restarting"] is False
