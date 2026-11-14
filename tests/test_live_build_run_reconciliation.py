"""Quiet live Build processes and pending recorders are not stale DB runs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.test_server_app_routes_init import _build_test_app, _start_client
from thomas.marketplace.observability import run_store
from thomas.server.app_keys import APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT
from thomas.server.routes import evolve_agent_run_state as state


def _create_old_run(run_id):
    run_store.create_run({"run_id": run_id, "mode": "code", "started_at": "2026-01-01T00:00:00+00:00"})


@pytest.mark.asyncio
async def test_real_janitor_keeps_live_and_recording_build_but_reaps_dead_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, "_DB_PATH", None)
    run_store.init_db(tmp_path / "runs.sqlite3")
    monkeypatch.setattr("thomas.server.app_routes_init._RUN_STORE_JANITOR_INTERVAL_SECONDS", 0.01)
    app, _ = _build_test_app(tmp_path, monkeypatch, run_store_enabled=True, run_store=run_store)
    live = SimpleNamespace(returncode=None)
    pending_save = asyncio.get_running_loop().create_future()
    app[state.APP_EVOLVE_AGENT_RUNS] = {
        "live-conversation": {"session": {"run_id": "live-build", "proc": live}},
        "saving-conversation": {
            "session": {"proc": SimpleNamespace(returncode=0)},
            "drain": {"run_id": "saving-build", "task": pending_save},
        },
        "dead-conversation": {"session": {"run_id": "dead-build", "proc": SimpleNamespace(returncode=1)}},
    }
    client = await _start_client(app)
    try:
        # Create rows after startup so the real periodic janitor is the only
        # cleanup path under test. None has a database event/heartbeat.
        for run_id in ("live-build", "saving-build", "dead-build", "orphan-build"):
            _create_old_run(run_id)
        for _ in range(100):
            if run_store.get_run("orphan-build")["run"]["ended_at"]:
                break
            await asyncio.sleep(0.01)
        for run_id in ("dead-build", "orphan-build"):
            row = run_store.get_run(run_id)["run"]
            assert row["ended_at"] and row["ok"] is False and row["error"].startswith("dead_run:")
        for run_id in ("live-build", "saving-build"):
            record = run_store.get_run(run_id)
            assert record["run"]["ended_at"] is None and record["run"]["ok"] is None
            assert record["events"] == []

        # A restart asked for while Build work is live is accepted and waits for that work (owner_restart.drain).
        accepted = await client.post("/api/server/restart")
        assert accepted.status == 202
        assert (await accepted.json())["restarting"] is True
        from thomas.server import owner_restart

        for _ in range(200):
            if "Build run" in owner_restart.status(app)["waiting_for"]:
                break
            await asyncio.sleep(0.01)
        assert "Build run" in owner_restart.status(app)["waiting_for"]
        assert app[APP_RESTART_REQUESTED] is False and not app[APP_SHUTDOWN_EVENT].is_set()

        # The exclusion is dynamic, not a forever whitelist of Build profiles.
        live.returncode = 1
        pending_save.set_result(None)
        for _ in range(100):
            if run_store.get_run("saving-build")["run"]["ended_at"]:
                break
            await asyncio.sleep(0.01)
        assert run_store.get_run("live-build")["run"]["ended_at"]
        assert run_store.get_run("saving-build")["run"]["ended_at"]
        for _ in range(500):
            if app[APP_SHUTDOWN_EVENT].is_set():
                break
            await asyncio.sleep(0.01)
        assert app[APP_SHUTDOWN_EVENT].is_set() and app[APP_RESTART_REQUESTED] is True
    finally:
        if not pending_save.done():
            pending_save.cancel()
        await client.close()


def test_stale_store_excludes_only_explicit_ids_without_changing_default(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, "_DB_PATH", None)
    run_store.init_db(tmp_path / "runs.sqlite3")
    for run_id in ("active", "orphan"):
        _create_old_run(run_id)
    assert run_store.reconcile_stale_runs(active_run_ids=frozenset({"active"})) == 1
    assert run_store.get_run("active")["run"]["ended_at"] is None
    assert run_store.get_run("orphan")["run"]["ended_at"]
    assert run_store.reconcile_stale_runs() == 1


@pytest.mark.asyncio
async def test_legacy_mirror_and_pending_save_use_same_active_identity():
    pending = asyncio.get_running_loop().create_future()
    app = {
        state.APP_EVOLVE_AGENT_CONVO: "legacy-conversation",
        state.APP_EVOLVE_AGENT_SESSION: {"run_id": "legacy-run"},
        state.APP_EVOLVE_AGENT_TASK: SimpleNamespace(returncode=None),
        state.APP_EVOLVE_AGENT_DRAIN: {"run_id": "legacy-run", "task": pending},
    }
    try:
        assert state.active_code_runs(app) == {"legacy-conversation": "legacy-run"}
        app[state.APP_EVOLVE_AGENT_TASK].returncode = 0
        assert state.active_code_runs(app) == {"legacy-conversation": "legacy-run"}
        pending.set_result(None)
        assert state.active_code_runs(app) == {}
    finally:
        if not pending.done():
            pending.cancel()
