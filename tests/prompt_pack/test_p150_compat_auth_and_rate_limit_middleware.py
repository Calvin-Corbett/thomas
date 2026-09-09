import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.gateway.p150_compat_auth_and_rate_limit_middleware import (
    CompatAuthConfig,
    CompatScopeConfig,
    RateLimitConfig,
    TokenBucketLimiter,
    build_compat_middlewares,
    compat_security_status_json,
)


@pytest.mark.asyncio
async def test_auth_rejects_missing_token_only_in_scope():
    scope = CompatScopeConfig(path_prefixes=("/v1",))
    auth = CompatAuthConfig(enabled=True, tokens=("abc",))
    rl = RateLimitConfig(enabled=False, rps=10.0, burst=20)
    mw_auth, mw_rl = build_compat_middlewares(scope=scope, auth=auth, ratelimit=rl)

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[mw_auth, mw_rl])
    app.router.add_get("/v1/test", handler)
    app.router.add_get("/internal/ok", handler)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        # In scope => 401
        resp = await client.get("/v1/test")
        assert resp.status == 401
        body = await resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "missing_bearer_token"

        # Out of scope => pass through
        resp2 = await client.get("/internal/ok")
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["ok"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_auth_accepts_valid_token():
    scope = CompatScopeConfig(path_prefixes=("/v1",))
    auth = CompatAuthConfig(enabled=True, tokens=("abc",))
    rl = RateLimitConfig(enabled=False, rps=10.0, burst=20)
    mw_auth, mw_rl = build_compat_middlewares(scope=scope, auth=auth, ratelimit=rl)

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[mw_auth, mw_rl])
    app.router.add_get("/v1/test", handler)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/v1/test", headers={"Authorization": "Bearer abc"})
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ratelimit_rejects_after_burst_exhausted_deterministic_clock_and_headers():
    # Deterministic time: never advances, so refill never happens.
    now_t = 1000.0

    def now():
        return now_t

    limiter = TokenBucketLimiter(rps=1.0, burst=2, now=now)
    scope = CompatScopeConfig(path_prefixes=("/v1",))
    auth = CompatAuthConfig(enabled=False, tokens=())
    rl = RateLimitConfig(enabled=True, rps=1.0, burst=2)
    mw_auth, mw_rl = build_compat_middlewares(scope=scope, auth=auth, ratelimit=rl, limiter=limiter)

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[mw_auth, mw_rl])
    app.router.add_get("/v1/test", handler)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        r1 = await client.get("/v1/test")
        assert r1.status == 200
        assert "X-RateLimit-Limit" in r1.headers
        assert "X-RateLimit-Remaining" in r1.headers

        r2 = await client.get("/v1/test")
        assert r2.status == 200

        r3 = await client.get("/v1/test")
        assert r3.status == 429
        assert "Retry-After" in r3.headers
        body = await r3.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "rate_limited"
    finally:
        await client.close()


def test_status_json_machine_readable():
    scope = CompatScopeConfig(path_prefixes=("/v1", "/compat"))
    auth = CompatAuthConfig(enabled=True, tokens=("a", "b"))
    rl = RateLimitConfig(enabled=True, rps=12.5, burst=99)
    payload = compat_security_status_json(scope, auth, rl)
    assert payload["ok"] is True
    assert payload["scope"]["path_prefixes"] == ["/v1", "/compat"]
    assert payload["auth"]["enabled"] is True
    assert payload["auth"]["tokens_configured"] == 2
    assert payload["ratelimit"]["enabled"] is True
    assert payload["ratelimit"]["rps"] == 12.5
    assert payload["ratelimit"]["burst"] == 99
