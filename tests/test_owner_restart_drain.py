"""Owner restart must wait for checks and report a real server generation."""

import asyncio

import pytest

from thomas.server import landed_code_reload as reload
from thomas.server import owner_restart as restart
from thomas.server.app_keys import APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT


@pytest.fixture
def drain(monkeypatch):
    app = {APP_SHUTDOWN_EVENT: asyncio.Event()}
    remembered = []

    async def finish(_app):
        remembered.append(True)

    async def waiting(_app):
        return ()

    monkeypatch.setattr(restart.landed_code_resume, "finish_drain", finish)
    monkeypatch.setattr(reload, "waiting_work", waiting)
    monkeypatch.setattr(reload, "active_work", lambda _app: ())
    monkeypatch.setattr(reload, "_signal_runs", lambda *_args: None)
    monkeypatch.setattr(restart.capacity_ledger, "rows", lambda: [])
    monkeypatch.setattr(restart, "POLL_S", 0.001)
    return app, remembered


@pytest.mark.asyncio
async def test_restart_waits_for_live_checks_then_restarts(drain, monkeypatch):
    app, remembered = drain
    rows = [
        {"id": "check-1", "kind": "check", "state": "admitted"},
        {"id": "shard:check-1:1", "kind": "pytest", "state": "admitted"},
    ]
    monkeypatch.setattr(restart.capacity_ledger, "rows", lambda: list(rows))
    initial = restart.status(app)
    accepted = restart.request_restart(app)
    task = app[restart.APP_OWNER_RESTART_TASK]
    try:
        assert restart.request_restart(app)["generation"] == accepted["generation"]
        assert app[restart.APP_OWNER_RESTART_TASK] is task
        for _ in range(100):
            if restart.status(app)["checks_running"] == 2:
                break
            await asyncio.sleep(0.005)
        assert restart.status(app)["checks_running"] == 2
        assert not app[APP_SHUTDOWN_EVENT].is_set()
        # Builds keep working while the checks finish: no gate on new starts yet (2026-11-13).
        assert reload.APP_LANDED_CODE_DRAIN not in app
        rows.clear()
        await asyncio.wait_for(task, 2)
        assert remembered, "the runs are remembered once the drain begins"
        assert app[APP_SHUTDOWN_EVENT].is_set()
        assert app[APP_RESTART_REQUESTED] is True
        assert restart.status(app)["generation"] == initial["generation"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unknown_check_ledger_never_requests_shutdown(drain, monkeypatch):
    app, _ = drain
    read = asyncio.Event()
    loop = asyncio.get_running_loop()

    def unavailable():
        loop.call_soon_threadsafe(read.set)
        raise OSError("ledger unavailable")

    monkeypatch.setattr(restart.capacity_ledger, "rows", unavailable)
    restart.request_restart(app)
    task = app[restart.APP_OWNER_RESTART_TASK]
    try:
        await asyncio.wait_for(read.wait(), 2)
        await asyncio.sleep(0.01)
        assert not app[APP_SHUTDOWN_EVENT].is_set()
        assert not app.get(APP_RESTART_REQUESTED)
        assert restart.status(app)["checks_running"] is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_status_reports_automatic_full_restart_and_changed_files(monkeypatch):
    monkeypatch.setattr(restart.time, "monotonic", lambda: 200)
    notice = {"files": ["thomas/server/app.py"], "reason": "Loaded server Python changed."}
    app = {
        reload.APP_LANDED_CODE_DRAIN: {"since": 20, "head": "landed"},
        "landed_code_notice": {"notice": notice},
    }
    status = restart.status(app)
    assert status["restarting"]
    assert status["elapsed_s"] == 180
    assert status["notice"] == notice
    assert status["generation"] == restart.status({})["generation"]


def test_automatic_drain_holds_when_ledger_is_unreadable(monkeypatch):
    def unavailable():
        raise OSError("ledger unavailable")

    monkeypatch.setattr(reload.capacity_ledger, "rows", unavailable)
    assert reload._checks_running() == -1
