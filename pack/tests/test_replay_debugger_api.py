# tests/test_replay_debugger_api.py
from __future__ import annotations

import os
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes import replay_debugger
from thomas.observability.run_db import ENV_DB_PATH
from tests._replay_test_db import init_db, seed_run

@pytest.mark.asyncio
async def test_replay_endpoints_seek_step_events(tmp_path: Path):
    db = tmp_path / "runs.sqlite3"
    init_db(db)
    seed_run(db)
    os.environ[ENV_DB_PATH] = str(db)

    app = web.Application()
    replay_debugger.setup(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/api/runs/run_test_1/events?start=0&limit=2")
        assert resp.status == 200
        data = await resp.json()
        assert data["total"] == 3
        assert len(data["events"]) == 2

        resp = await client.post("/api/runs/run_test_1/replay/seek", json={"index": 0})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["event"]["index"] == 0

        resp = await client.post("/api/runs/run_test_1/replay/step", json={"index": 0, "delta": 1})
        data = await resp.json()
        assert data["ok"] is True
        assert data["event"]["index"] == 1

        resp = await client.post("/api/runs/run_test_1/replay/step", json={"index": 1, "delta": -1})
        data = await resp.json()
        assert data["ok"] is True
        assert data["event"]["index"] == 0
    finally:
        await client.close()
