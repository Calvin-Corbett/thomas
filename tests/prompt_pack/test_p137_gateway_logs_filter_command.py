from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.gateway import p137_gateway_logs_filter_command as route_mod


async def _make_client(app: web.Application) -> TestClient:
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_gateway_logs_filter_success_contains(tmp_path: Path):
    log_file = tmp_path / "gateway.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-02-20T12:00:00Z INFO gateway started",
                "2026-02-20T12:00:01Z ERROR bad thing happened",
                '{"timestamp": "2026-02-20T12:00:02Z", "level": "INFO", "msg": "json ok"}',
                "2026-02-20T12:00:03Z ERROR another bad thing",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = web.Application()
    app[route_mod.CONFIG_APP_KEY] = {"gateway_log_path": str(log_file)}
    app.add_routes(route_mod.routes)

    client = await _make_client(app)
    try:
        resp = await client.post("/gateway/logs/filter", json={"contains": "ERROR", "limit": 10})
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        assert payload["truncated"] is False
        texts = [m["text"] for m in payload["matches"]]
        assert any("bad thing happened" in t for t in texts)
        assert any("another bad thing" in t for t in texts)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_logs_filter_newest_first_ring_buffer(tmp_path: Path):
    log_file = tmp_path / "gateway.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-02-20T12:00:00Z ERROR e1",
                "2026-02-20T12:00:01Z ERROR e2",
                "2026-02-20T12:00:02Z ERROR e3",
                "2026-02-20T12:00:03Z ERROR e4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = web.Application()
    app[route_mod.CONFIG_APP_KEY] = {"gateway_log_path": str(log_file)}
    app.add_routes(route_mod.routes)

    client = await _make_client(app)
    try:
        resp = await client.post("/gateway/logs/filter", json={"contains": "ERROR", "limit": 2, "newest_first": True})
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        assert payload["truncated"] is True  # there were more than 2 matches
        texts = [m["text"] for m in payload["matches"]]
        # newest first means e4 then e3
        assert texts[0].endswith("e4")
        assert texts[1].endswith("e3")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_logs_filter_invalid_regex_returns_deterministic_error(tmp_path: Path):
    log_file = tmp_path / "gateway.log"
    log_file.write_text("2026-02-20T12:00:00Z INFO hello\n", encoding="utf-8")

    app = web.Application()
    app[route_mod.CONFIG_APP_KEY] = {"gateway_log_path": str(log_file)}
    app.add_routes(route_mod.routes)

    client = await _make_client(app)
    try:
        resp = await client.post("/gateway/logs/filter", json={"regex": "["})
        assert resp.status == 400
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "INVALID_INPUT"
        assert "regex" in payload["error"]["fields"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_logs_filter_missing_config_returns_deterministic_error():
    app = web.Application()
    app.add_routes(route_mod.routes)

    client = await _make_client(app)
    try:
        resp = await client.post("/gateway/logs/filter", json={"contains": "anything"})
        assert resp.status == 500
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "MISSING_CONFIG"
    finally:
        await client.close()
