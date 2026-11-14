"""Restart boundaries must not consume same-server drain recovery entries."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import landed_code_resume as recovery
from thomas.server.app_keys import APP_RESTART_REQUESTED


@pytest.fixture
def isolated_recovery(monkeypatch, tmp_path):
    run = recovery.DrainRun(Path(tmp_path), "run-1", "request-1")
    pending = {"conversation-1": run}
    app = {recovery.APP_DRAIN_RUNS: pending}
    monkeypatch.setattr(recovery.workers, "generation_stopping", lambda: False)
    monkeypatch.setattr(recovery.thomas_project, "_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(recovery, "active_code_runs", lambda _app: {})
    monkeypatch.setattr(recovery.machine_capacity, "admission_refusal", lambda _count: None)
    monkeypatch.setattr(recovery.autopilot_restart, "_cage_down", lambda: False)
    return app, pending, run


def begin_restart(app, signal):
    if signal == "owner":
        app["owner_restart"] = {"restarting": True}
    else:
        app[APP_RESTART_REQUESTED] = True


@pytest.mark.parametrize("signal", ["owner", "requested"])
def test_can_resume_blocks_each_restart_signal(isolated_recovery, signal):
    app, _, _ = isolated_recovery
    assert recovery._can_resume(app)
    begin_restart(app, signal)
    assert not recovery._can_resume(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["owner", "requested"])
@pytest.mark.parametrize("found", [False, True])
async def test_restart_during_yielded_read_keeps_pending(isolated_recovery, monkeypatch, signal, found):
    app, pending, run = isolated_recovery
    entered, release = asyncio.Event(), asyncio.Event()
    item = SimpleNamespace(turn={"text": "original"}) if found else None
    calls = []

    async def read(*_args):
        entered.set()
        await release.wait()
        return item

    async def carry_on(*args, **kwargs):
        calls.append((args, kwargs))
        return "started", "ok"

    monkeypatch.setattr(recovery.asyncio, "to_thread", read)
    monkeypatch.setattr(recovery.autopilot_restart, "_carry_on", carry_on)
    task = asyncio.create_task(recovery.resume(app))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        begin_restart(app, signal)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=2)
    assert pending == {"conversation-1": run}
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["owner", "requested"])
async def test_restart_during_carry_on_keeps_pending(isolated_recovery, monkeypatch, signal):
    app, pending, run = isolated_recovery
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(*_args):
        return SimpleNamespace(turn={"text": "original"})

    async def carry_on(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return "started", "ok"

    monkeypatch.setattr(recovery.asyncio, "to_thread", read)
    monkeypatch.setattr(recovery.autopilot_restart, "_carry_on", carry_on)
    task = asyncio.create_task(recovery.resume(app))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        begin_restart(app, signal)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=2)
    assert pending == {"conversation-1": run}
