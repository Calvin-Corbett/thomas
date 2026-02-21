# tests/test_replay_middleware_records_run.py
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.observability.run_db import ENV_DB_PATH
from thomas.observability.run_store_replay import count_events
from thomas.server.middleware.replay_observability import replay_observability_middleware

def test_middleware_creates_run_and_records_http(tmp_path: Path):
    async def _run() -> None:
        db = tmp_path / "runs.sqlite3"
        os.environ[ENV_DB_PATH] = str(db)

        async def handler(request: web.Request):
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[replay_observability_middleware])
        app.router.add_post("/api/chat", handler)

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/api/chat", json={"msg": "hi"})
            assert resp.status == 200
            rid = resp.headers.get("X-Thomas-Run-Id")
            assert rid is not None
            # Should have at least http.request + http.response
            assert count_events(rid) >= 2
        finally:
            await client.close()

    asyncio.run(_run())
