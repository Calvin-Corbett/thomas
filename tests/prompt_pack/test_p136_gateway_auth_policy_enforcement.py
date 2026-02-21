import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

from thomas.server.routes.gateway import p136_gateway_auth_policy_enforcement as gw
from thomas.cli.commands.gateway import p136_gateway_auth_policy_enforcement as cli


async def _make_client(app: web.Application) -> TestClient:
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_gateway_auth_disabled_allows_requests(monkeypatch):
    monkeypatch.delenv("THOMAS_GATEWAY_AUTH_MODE", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_AUTH_TOKENS", raising=False)

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)
    client = await _make_client(app)
    try:
        resp = await client.get("/gateway/echo")
        assert resp.status == 200
        assert await resp.json() == {"ok": True}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_token_required_enforced(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)
    app.router.add_get("/gateway/auth/policy", gw.get_gateway_auth_policy)

    client = await _make_client(app)
    try:
        resp = await client.get("/gateway/auth/policy")
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        assert payload["policy"]["required"] is True
        assert payload["policy"]["token_configured"] is True
        assert payload["policy"]["rate_limit"]["enabled"] is True
        assert payload["policy"]["rate_limit"]["max_failures"] == 8

        resp = await client.get("/gateway/echo")
        assert resp.status == 401
        body = await resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "gateway_auth_missing"

        resp = await client.get("/gateway/echo", headers={"Authorization": "Bearer nope"})
        assert resp.status == 401
        body = await resp.json()
        assert body["error"]["code"] == "gateway_auth_invalid"

        resp = await client.get("/gateway/echo", headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status == 200
        assert await resp.json() == {"ok": True}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_misconfigured_returns_deterministic_error(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.delenv("THOMAS_GATEWAY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_GATEWAY_AUTH_TOKENS", raising=False)

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)

    client = await _make_client(app)
    try:
        resp = await client.get("/gateway/echo")
        assert resp.status == 500
        body = await resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "gateway_auth_misconfigured"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_gateway_path_not_blocked_in_auto_scope(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_SCOPE", "auto")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/healthz", ok)

    client = await _make_client(app)
    try:
        resp = await client.get("/healthz")
        assert resp.status == 200
        assert await resp.json() == {"ok": True}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_rate_limited_after_repeated_invalid_tokens(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES", "2")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)

    client = await _make_client(app)
    try:
        for _ in range(2):
            resp = await client.get("/gateway/echo", headers={"Authorization": "Bearer nope"})
            assert resp.status == 401
            body = await resp.json()
            assert body["error"]["code"] == "gateway_auth_invalid"

        limited = await client.get("/gateway/echo", headers={"Authorization": "Bearer nope"})
        assert limited.status == 429
        assert limited.headers.get("Retry-After")
        body = await limited.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "gateway_auth_rate_limited"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_rate_limited_even_when_token_values_rotate(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES", "2")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)

    client = await _make_client(app)
    try:
        first = await client.get("/gateway/echo", headers={"Authorization": "Bearer bad-1"})
        assert first.status == 401

        second = await client.get("/gateway/echo", headers={"Authorization": "Bearer bad-2"})
        assert second.status == 401

        third = await client.get("/gateway/echo", headers={"Authorization": "Bearer bad-3"})
        assert third.status == 429
        body = await third.json()
        assert body["error"]["code"] == "gateway_auth_rate_limited"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_rate_limit_can_be_disabled(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES", "1")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)

    client = await _make_client(app)
    try:
        first = await client.get("/gateway/echo", headers={"Authorization": "Bearer nope"})
        assert first.status == 401
        second = await client.get("/gateway/echo", headers={"Authorization": "Bearer nope"})
        assert second.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_rate_limited_after_repeated_missing_tokens(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "s3cr3t")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES", "2")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")

    app = web.Application(middlewares=[gw.gateway_auth_policy_middleware])

    async def ok(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/gateway/echo", ok)

    client = await _make_client(app)
    try:
        first = await client.get("/gateway/echo")
        assert first.status == 401
        first_body = await first.json()
        assert first_body["error"]["code"] == "gateway_auth_missing"

        second = await client.get("/gateway/echo")
        assert second.status == 401
        second_body = await second.json()
        assert second_body["error"]["code"] == "gateway_auth_missing"

        third = await client.get("/gateway/echo")
        assert third.status == 429
        assert third.headers.get("Retry-After")
        third_body = await third.json()
        assert third_body["error"]["code"] == "gateway_auth_rate_limited"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_auth_rate_limit_buckets_isolated_by_remote_identity():
    policy = gw.GatewayAuthPolicy(
        mode="token",
        tokens=("s3cr3t",),
        rate_limit_enabled=True,
        rate_limit_max_failures=1,
        rate_limit_window_seconds=60,
    )
    app = web.Application()

    class DummyRequest:
        def __init__(self, remote: str, token: str) -> None:
            self.app = app
            self.remote = remote
            self.headers = {"Authorization": f"Bearer {token}"}
            self.rel_url = URL("/gateway/echo")
            self.cookies = {}

    first_remote = DummyRequest("203.0.113.10", "bad-1")
    second_remote = DummyRequest("203.0.113.11", "bad-2")

    assert await gw._consume_auth_failure_rate_limit(first_remote, policy) is None
    assert await gw._consume_auth_failure_rate_limit(first_remote, policy) is not None
    assert await gw._consume_auth_failure_rate_limit(second_remote, policy) is None


def test_cli_json_output(monkeypatch, capsys):
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_TOKEN", "cli-secret")
    monkeypatch.setenv("THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES", "4")

    rc = cli.main(["--token", "cli-secret", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["allowed"] is True
    assert payload["code"] == "gateway_auth_ok"
    assert payload["policy"]["rate_limit"]["max_failures"] == 4

    rc = cli.main(["--token", "nope", "--json"])
    assert rc == 2
    _ = capsys.readouterr().out

    rc = cli.main(["--describe", "--json"])
    assert rc == 0
    described = json.loads(capsys.readouterr().out)
    assert described["rate_limit"]["max_failures"] == 4
