import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.gateway import p139_openai_compat_route_scaffold as route_mod


@pytest.mark.asyncio
async def test_schema_endpoint_success_root_mount():
    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get(f"{route_mod.BASE_PATH}/schema")
        assert resp.status == 200
        data = await resp.json()

    assert data["id"] == "gateway.openai_compat"
    assert any(r["path"].endswith("/v1/chat/completions") for r in data["routes"])
    # Advertised external base path should be the gateway-prefixed one.
    assert all(r["path"].startswith(route_mod.GATEWAY_BASE_PATH) for r in data["routes"])


@pytest.mark.asyncio
async def test_schema_endpoint_success_gateway_subapp_mount():
    parent = web.Application()
    sub = web.Application()
    route_mod.register(sub)
    parent.add_subapp("/gateway", sub)

    async with TestServer(parent) as server, TestClient(server) as client:
        resp = await client.get(f"{route_mod.GATEWAY_BASE_PATH}/schema")
        assert resp.status == 200
        data = await resp.json()

    assert data["id"] == "gateway.openai_compat"


@pytest.mark.asyncio
async def test_health_missing_config_is_deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THOMAS_GATEWAY_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_OPENAI_BASE_URL", raising=False)

    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get(f"{route_mod.BASE_PATH}/health")
        assert resp.status == 503
        data = await resp.json()

    assert data == {
        "error": {
            "message": "Missing upstream base URL for OpenAI-compatible proxy.",
            "type": "configuration_error",
            "param": None,
            "code": "thomas_missing_openai_base_url",
        }
    }


@pytest.mark.asyncio
async def test_proxy_success_and_invalid_json(monkeypatch: pytest.MonkeyPatch):
    # Upstream stub (OpenAI-compatible surface).
    async def upstream_ok(request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer sk-test"
        payload = await request.json()
        assert payload["model"] == "gpt-test"
        return web.json_response(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    upstream_app = web.Application()
    upstream_app.router.add_post("/v1/chat/completions", upstream_ok)

    async with TestServer(upstream_app) as upstream_server:
        upstream_base = str(upstream_server.make_url("/")).rstrip("/")
        monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_BASE_URL", upstream_base)
        monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_API_KEY", "sk-test")

        gateway_app = web.Application()
        route_mod.register(gateway_app)

        async with TestServer(gateway_app) as gateway_server, TestClient(gateway_server) as client:
            resp = await client.post(
                f"{route_mod.BASE_PATH}/v1/chat/completions",
                json={"model": "gpt-test", "messages": [{"role": "user", "content": "yo"}]},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == "chatcmpl-test"
            assert data["model"] == "gpt-test"

    # Deterministic error for invalid JSON body.
    monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_API_KEY", "sk-test")

    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            f"{route_mod.BASE_PATH}/v1/chat/completions",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()

    assert data["error"]["code"] == "thomas_invalid_json"


@pytest.mark.asyncio
async def test_proxy_upstream_unreachable_is_deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("THOMAS_GATEWAY_OPENAI_TIMEOUT_S", "0.2")

    app = web.Application()
    route_mod.register(app)

    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            f"{route_mod.BASE_PATH}/v1/chat/completions",
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "yo"}]},
        )
        assert resp.status == 502
        data = await resp.json()

    assert data["error"]["code"] == "thomas_upstream_unreachable"
