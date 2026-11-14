"""``GET /api/version`` belongs to the server itself, so no plugin switch reaches it.

It used to be registered by ``thomas.server.routes.models_aiohttp``, beside the model routes. The boot probes and the
debug dock ask it, so it moved to ``thomas.server.routes.version_aiohttp`` and the shell's own table, ahead of the
models row (``thomas.server.rows.models``) becoming something you can turn off.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_proof_fixture import choose
from thomas.server import app_core


@pytest.fixture
def every_row_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    choose(data, on=[])
    return tmp_path


def test_with_every_row_off_the_version_route_still_answers_from_the_servers_own_table(every_row_off: Path) -> None:
    async def scenario() -> tuple[int, dict[str, Any], list[str], list[str]]:
        app = app_core.create_app(views.config_in(every_row_off))
        async with TestClient(TestServer(app)) as client:
            answered = await client.get("/api/version")
            live = sorted(f"{r.method} {r.resource.canonical}" for r in app.router._live.routes() if r.resource)
            shell = sorted(f"{r.method} {r.resource.canonical}" for r in app.router.server_routes() if r.resource)
            return answered.status, await answered.json(), live, shell

    status, body, live, shell = asyncio.run(scenario())

    assert status == 200
    assert set(body) == {"version", "runtime_guard", "runtime_mode"}
    assert "GET /api/version" not in live
    assert "GET /api/version" in shell


def test_the_model_routes_no_longer_register_it() -> None:
    from thomas.server.routes import models_aiohttp

    assert not hasattr(models_aiohttp, "_runtime_guard_payload")
    assert "api/version" not in Path(models_aiohttp.__file__).read_text(encoding="utf-8")
