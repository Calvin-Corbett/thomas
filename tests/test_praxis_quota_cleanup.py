"""Build cleanup must retain interrupted children except for an explicit Stop."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.server.praxis.launch import attach_cleanup
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


async def _open_parked(app, journal, run_id):
    registry = register_praxis_run_routes(app)

    async def child(_agent_id, _kind, _title, _brief):
        yield {
            "type": "error",
            "error": "account quota",
            "retryable": True,
            "provider_credential": "opaque-account",
            "quota": {"kind": "quota", "retry_at": time.time() + 60, "reason": "provider_quota"},
        }

    channel = registry.open(run_id, child, journal=journal)
    child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]
    for _ in range(100):
        if channel.status([child_id])["agents"][0]["state"] == "quota_wait":
            break
        await asyncio.sleep(0.001)
    assert channel.status([child_id])["agents"][0]["state"] == "quota_wait"
    return registry, channel, child_id


@pytest.mark.asyncio
async def test_normal_lead_exit_revokes_channel_but_preserves_quota_continuation(tmp_path):
    app = web.Application()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    registry, channel, child_id = await _open_parked(app, journal, "run")
    proc = SimpleNamespace(returncode=0)
    lead_task = asyncio.create_task(asyncio.sleep(0))
    attach_cleanup(app, lead_task, "run", proc)
    await lead_task
    for _ in range(100):
        if "run" not in registry._runs:
            break
        await asyncio.sleep(0.001)
    assert "run" not in registry._runs
    assert not channel.authorized(channel.token)
    saved = journal.load("run")["children"][0]
    assert saved["agent_id"] == child_id
    assert saved["state"] == "quota_wait"
    assert journal.interrupted_runs() == ["run"]


@pytest.mark.asyncio
async def test_explicit_stop_terminalizes_parked_child(tmp_path):
    app = web.Application()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    registry, _channel, _child_id = await _open_parked(app, journal, "stopped")
    proc = SimpleNamespace(returncode=-1, thomas_stop_requested="stop")
    lead_task = asyncio.create_task(asyncio.sleep(0))
    attach_cleanup(app, lead_task, "stopped", proc)
    await lead_task
    for _ in range(100):
        if "stopped" not in registry._runs and journal.load("stopped")["children"][0]["state"] == "stopped":
            break
        await asyncio.sleep(0.001)
    assert journal.load("stopped")["children"][0]["state"] == "stopped"
    assert journal.interrupted_runs() == []


@pytest.mark.asyncio
async def test_server_cleanup_suspends_without_terminalizing(tmp_path):
    app = web.Application()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    registry, _channel, _child_id = await _open_parked(app, journal, "restart")
    await app.on_cleanup[-1](app)
    assert "restart" not in registry._runs
    assert journal.load("restart")["children"][0]["state"] == "quota_wait"
