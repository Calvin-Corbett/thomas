"""A block type Thomas refuses to switch is named in the refusal, beside the reason.

``POST /api/display/types/{type}`` answered ``{"error": "..."}`` alone for a bad name; a page showing that could say why
but not which type. The display row's route now answers ``{"error": ..., "type": <what was sent>}``. This landing is
also the first row-only Python change after plugin-row hot swap (650792728): the running server swaps the display row
in place instead of restarting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.display_routes import register_display_routes


def test_a_bad_type_name_comes_back_with_the_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))

    async def scenario() -> None:
        app = web.Application()
        register_display_routes(app, require_api_access=lambda _request: None)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            refused = await client.post("/api/display/types/Not%20A%20Type", json={"enabled": False})
            assert refused.status == 400
            answer = await refused.json()
            assert answer["type"] == "Not A Type"
            assert "lowercase" in answer["error"]
            switched = await client.post("/api/display/types/table", json={"enabled": False})
            assert switched.status == 200
            assert (await switched.json()) == {"disabled": ["table"]}
        finally:
            await client.close()

    asyncio.run(scenario())
