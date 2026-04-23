import json
from dataclasses import asdict

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.gateway import p144_responses_compat_route_scaffold as route_mod
from thomas.cli.commands.gateway import p144_responses_compat_route_scaffold as cli_mod


@pytest.mark.asyncio
async def test_schema_endpoint_returns_json():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/v1/responses/schema")
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "responses_compat"
            assert any(r["path"] == "/v1/responses" for r in data["routes"])
            assert "request_schema" in data
            assert "response_schema" in data


@pytest.mark.asyncio
async def test_create_stub_success_default_mode(monkeypatch):
    # Ensure we do not accidentally pick up a global proxy config.
    monkeypatch.delenv("THOMAS_RESPONSES_COMPAT_MODE", raising=False)
    monkeypatch.delenv("THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/v1/responses", json={"model": "test-model", "input": "hello"})
            assert resp.status == 200
            data = await resp.json()
            assert data["object"] == "response"
            assert data["model"] == "test-model"
            assert data["status"] == "completed"
            assert isinstance(data["output"], list)
            assert data["output"][0]["content"][0]["type"] == "output_text"
            assert data["output"][0]["content"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_create_rejects_stream_mode():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/v1/responses", json={"model": "m", "input": "x", "stream": True})
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["code"] == "not_supported"
            assert data["error"]["param"] == "stream"


@pytest.mark.asyncio
async def test_create_invalid_missing_model():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/v1/responses", json={"input": "x"})
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["type"] == "invalid_request_error"
            assert data["error"]["code"] == "missing_field"
            assert data["error"]["param"] == "model"


@pytest.mark.asyncio
async def test_create_invalid_input_shape():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/v1/responses", json={"model": "m", "input": [{"wat": 1}]})
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["code"] == "invalid_input_item"
            assert data["error"]["param"] == "input"


@pytest.mark.asyncio
async def test_create_invalid_json_body():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post(
                "/v1/responses",
                data=b"{not-json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["code"] == "invalid_json"


@pytest.mark.asyncio
async def test_create_proxy_missing_config_returns_deterministic_error(monkeypatch):
    monkeypatch.setenv("THOMAS_RESPONSES_COMPAT_MODE", "proxy")
    monkeypatch.delenv("THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL", raising=False)

    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/v1/responses", json={"model": "m", "input": "x"})
            assert resp.status == 500
            data = await resp.json()
            assert data["error"]["type"] == "configuration_error"
            assert data["error"]["code"] == "missing_config"


@pytest.mark.asyncio
async def test_create_proxy_forwards_to_upstream(monkeypatch):
    upstream_app = web.Application()

    async def upstream_handler(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response(
            {
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": payload.get("model", "unknown"),
                "status": "completed",
                "output": [],
            }
        )

    upstream_app.router.add_post("/v1/responses", upstream_handler)

    async with TestServer(upstream_app) as upstream_server:
        upstream_url = str(upstream_server.make_url("")).rstrip("/")

        monkeypatch.setenv("THOMAS_RESPONSES_COMPAT_MODE", "proxy")
        monkeypatch.setenv("THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL", upstream_url)

        app = web.Application()
        route_mod.register(app)

        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.post("/v1/responses", json={"model": "m1", "input": "x"})
                assert resp.status == 200
                data = await resp.json()
                assert data["id"] == "resp_test"
                assert data["model"] == "m1"


def test_cli_report_json_is_machine_readable():
    report = cli_mod.build_report()
    payload = asdict(report)
    payload = json.loads(json.dumps(payload))
    assert payload["name"] == "responses_compat"
    assert "request_schema" in payload["schema"]
