"""The route that cancels a waiting restart is a row (``thomas.server.rows.restart_cancel``), not a route of the shell.

It was first added to the shell in ``app_routes_init.py``, which put the shell one route over what
``tests/test_the_shell_adds_no_routes.py`` allows. Its registrar is ``thomas.server.routes.restart_cancel_routes``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.restart_cancel_routes import register_restart_cancel_routes

ROOT = Path(__file__).resolve().parents[1]


async def _client(require_loopback) -> TestClient:
    app = web.Application()
    register_restart_cancel_routes(app, require_loopback=require_loopback)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_cancelling_with_no_restart_waiting_answers_ok_and_idle() -> None:
    client = await _client(lambda request: None)
    try:
        answer = await client.post("/api/server/restart/cancel")
        body = await answer.json()
    finally:
        await client.close()
    assert answer.status == 200
    assert body["ok"] is True and body["restarting"] is False and body["phase"] == "idle"


@pytest.mark.asyncio
async def test_a_caller_from_another_computer_is_refused_before_anything_is_cancelled() -> None:
    def refuse(request: web.Request) -> None:
        raise web.HTTPForbidden(text="This endpoint is only available from localhost.")

    client = await _client(refuse)
    try:
        answer = await client.post("/api/server/restart/cancel")
    finally:
        await client.close()
    assert answer.status == 403


def test_the_shell_no_longer_registers_it() -> None:
    shell = (ROOT / "thomas/server/app_routes_init.py").read_text(encoding="utf-8")
    assert "restart/cancel" not in shell


def test_the_row_is_listed_and_has_no_off_switch() -> None:
    import tomllib

    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text(encoding="utf-8"))["row"]
    mine = [row for row in rows if row["id"] == "restart_cancel"]
    assert len(mine) == 1
    assert mine[0]["entry"] == "thomas.server.rows.restart_cancel:plugin"
    assert mine[0].get("required") is True
