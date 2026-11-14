"""GET /api/ratchet reads the ratchet's records; POST /api/ratchet/run starts a run in the background.

These routes are the row ``thomas.server.rows.ratchet`` now, and that dotted name here is how a check of the row finds
this file. ``tests/test_turning_ratchet_off_touches_only_its_routes.py`` holds the row itself.
"""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.service import ACCOUNT_ENV, RatchetService
from thomas.server.routes.ratchet_routes import APP_RATCHET, register_ratchet_routes


def _drive(body):  # noqa: ANN001, ANN202
    async def run():  # noqa: ANN202
        app = web.Application()
        register_ratchet_routes(app, service=RatchetService(app), require_api_access=lambda _request: None)
        async with TestClient(TestServer(app)) as client:
            return await body(app, client)

    return asyncio.run(run())


def test_the_report_lists_every_candidate_with_its_state_and_reason() -> None:
    Ledger().record(
        sha="a" * 40,
        refs=["refs/heads/fix/a"],
        dev_sha="d" * 40,
        state="reported",
        reason="1 new failure(s): tests/test_a.py::test_a",
    )

    async def body(app, client):  # noqa: ANN001, ANN202
        resp = await client.get("/api/ratchet")
        assert resp.status == 200
        data = await resp.json()
        assert data["candidates"][0]["ref"] == "refs/heads/fix/a"
        assert data["candidates"][0]["reason"].startswith("1 new failure(s)")
        assert data["running"] is False and data["halted"] == {}

    _drive(body)


def test_a_run_starts_in_the_background_and_a_second_one_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, getpass.getuser())
    seen = []

    async def body(app, client):  # noqa: ANN001, ANN202
        release = asyncio.Event()

        async def fake_run_once(self, *, limit, chat):  # noqa: ANN001, ANN202
            seen.append((limit, chat))
            await release.wait()
            return {"status": "ran", "proven": []}

        monkeypatch.setattr(RatchetService, "run_once", fake_run_once)
        first = await client.post("/api/ratchet/run", json={"limit": 2, "chat_session_id": "chat-1"})
        second = await client.post("/api/ratchet/run", json={})
        release.set()
        await asyncio.sleep(0)
        assert first.status == 202 and (await first.json())["status"] == "started"
        assert second.status == 409 and (await second.json())["code"] == "ratchet_busy"
        assert seen == [(2, "chat-1")]
        assert app[APP_LOCAL_PORT] > 0

    _drive(body)


def test_a_run_is_refused_outside_the_caged_thomas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACCOUNT_ENV, "somebody-else")

    async def body(app, client):  # noqa: ANN001, ANN202
        resp = await client.post("/api/ratchet/run", json={})
        assert resp.status == 409 and (await resp.json())["code"] == "ratchet_not_here"

    _drive(body)


def test_the_server_itself_serves_the_ratchet(tmp_path: Path) -> None:
    """Built by the real app factory, not a bare Application: the row is proven here, where a failed import would
    otherwise leave every other route test green. The row is on and the service it wrote has the real app, not a view."""
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
        server=ServerConfig(access_mode="local"),
    )

    async def run() -> None:
        app = create_app(cfg)
        async with TestClient(TestServer(app)) as client:
            origin = str(client.make_url("/")).rstrip("/")
            resp = await client.get("/api/ratchet", headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
            assert resp.status == 200 and "candidates" in await resp.json()
            assert app[APP_RATCHET].app is app

    asyncio.run(run())
