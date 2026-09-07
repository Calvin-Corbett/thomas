"""Regression tests for the same-origin guard on mutating API requests.

A browser opened at ``http://localhost:<port>`` sends ``Origin:
http://localhost:<port>``. The guard used to feed that host straight into
``ipaddress.ip_address()``, which raises ``ValueError`` for the *name*
"localhost", so the origin was treated as cross-origin and every mutating
request 403'd. GETs were unaffected, so the UI looked fine and then silently
failed on every save/send/approve.

RFC 6761 reserves "localhost" (and any "*.localhost" name) to always resolve to
a loopback address, so these are same-machine origins by definition.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from thomas.core.config import load_config
from thomas.server.app_keys import APP_CONFIG, APP_REQUIRE_API_ACCESS
from thomas.server.app_middleware_handlers import setup_middleware_and_handlers


class _LoopbackTransport:
    def get_extra_info(self, name: str, default=None):
        if name == "peername":
            return ("127.0.0.1", 12345)
        return default


async def _build_app(tmp_path: Path, *, access_mode: str = "local") -> web.Application:
    app = web.Application()
    config = load_config()
    config.server.access_mode = access_mode
    config.server.api_token = "remote-secret" if access_mode == "remote" else ""
    app[APP_CONFIG] = config
    web_dir = tmp_path / "web"
    chat_dir = tmp_path / "chat"
    web_dir.mkdir(parents=True, exist_ok=True)
    chat_dir.mkdir(parents=True, exist_ok=True)

    setup_middleware_and_handlers(app, config, web_dir, chat_dir, asyncio.Lock())

    async def probe(request: web.Request) -> web.Response:
        # Mirrors how real mutating routes gate themselves.
        guard = request.app[APP_REQUIRE_API_ACCESS]
        guard(request)
        return web.json_response({"ok": True})

    app.router.add_post("/api/_origin_probe", probe)
    return app


async def _post_with_origin(client: TestClient, origin: str | None):
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    return await client.post("/api/_origin_probe", json={}, headers=headers)


@pytest.mark.asyncio
async def test_localhost_name_origin_is_allowed_for_mutating_request(tmp_path: Path) -> None:
    """The regression: Origin host "localhost" must not be treated as cross-origin."""
    app = await _build_app(tmp_path)
    server = TestServer(app)
    await server.start_server()
    try:
        client = TestClient(server)
        await client.start_server()
        port = server.port
        resp = await _post_with_origin(client, f"http://localhost:{port}")
        assert resp.status == 200, await resp.text()
        await client.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_loopback_ip_origin_is_allowed_for_mutating_request(tmp_path: Path) -> None:
    """The path that already worked keeps working."""
    app = await _build_app(tmp_path)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        client = TestClient(server)
        await client.start_server()
        port = server.port
        resp = await _post_with_origin(client, f"http://127.0.0.1:{port}")
        assert resp.status == 200, await resp.text()
        await client.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_foreign_origin_is_still_rejected(tmp_path: Path) -> None:
    """The fix must not open the guard up to genuinely cross-origin callers."""
    app = await _build_app(tmp_path)
    server = TestServer(app)
    await server.start_server()
    try:
        client = TestClient(server)
        await client.start_server()
        resp = await _post_with_origin(client, "http://evil.example.com")
        assert resp.status == 403, await resp.text()
        await client.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_non_loopback_lookalike_origin_is_rejected(tmp_path: Path) -> None:
    """ "notlocalhost" and "localhost.evil.com" must not slip through the name check."""
    app = await _build_app(tmp_path)
    server = TestServer(app)
    await server.start_server()
    try:
        client = TestClient(server)
        await client.start_server()
        for host in ("http://notlocalhost:8899", "http://localhost.evil.com"):
            resp = await _post_with_origin(client, host)
            assert resp.status == 403, f"{host} -> {resp.status}: {await resp.text()}"
        await client.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_local_mode_accepts_only_intended_local_host_authorities(tmp_path: Path) -> None:
    app = await _build_app(tmp_path)
    guard = app[APP_REQUIRE_API_ACCESS]
    allowed = (
        "localhost",
        "localhost:8899",
        "thomas.localhost:8899",
        "127.0.0.1",
        "127.0.0.42:8899",
        "[::1]:8899",
        "10.0.2.2:8899",
        "10.0.3.2",
    )
    for authority in allowed:
        request = make_mocked_request(
            "GET",
            "/api/_host_probe",
            headers={"Host": authority, "Sec-Fetch-Site": "same-origin"},
            app=app,
            transport=_LoopbackTransport(),
        )
        guard(request)


@pytest.mark.asyncio
async def test_local_mode_rejects_foreign_and_malformed_host_authorities(tmp_path: Path) -> None:
    app = await _build_app(tmp_path)
    guard = app[APP_REQUIRE_API_ACCESS]
    rejected = (
        "evil.example:8899",
        "localhost.evil.example",
        "127.0.0.1.evil.example",
        "bad host",
        "user@localhost",
        "localhost/path",
        "localhost:",
        "localhost:0",
        "localhost:65536",
        "[::1",
        "::1",
        "[127.0.0.1]",
        "10.0.2.3",
    )
    for authority in rejected:
        request = make_mocked_request(
            "GET",
            "/api/_host_probe",
            headers={"Host": authority, "Sec-Fetch-Site": "same-origin"},
            app=app,
            transport=_LoopbackTransport(),
        )
        with pytest.raises(web.HTTPForbidden):
            guard(request)


@pytest.mark.asyncio
async def test_local_mode_rejects_missing_and_ambiguous_host_headers(tmp_path: Path) -> None:
    app = await _build_app(tmp_path)
    guard = app[APP_REQUIRE_API_ACCESS]
    requests = (
        make_mocked_request(
            "GET",
            "/api/_host_probe",
            headers={"Sec-Fetch-Site": "same-origin"},
            app=app,
            transport=_LoopbackTransport(),
        ),
        make_mocked_request(
            "GET",
            "/api/_host_probe",
            headers=[
                ("Host", "localhost"),
                ("Host", "evil.example"),
                ("Sec-Fetch-Site", "same-origin"),
            ],
            app=app,
            transport=_LoopbackTransport(),
        ),
    )
    for request in requests:
        with pytest.raises(web.HTTPForbidden):
            guard(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["evil.example:8899", "bad host"])
async def test_configured_csrf_token_does_not_restore_host_header_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
) -> None:
    monkeypatch.setenv("THOMAS_MUTATING_CSRF_TOKEN", "audit-secret")
    app = await _build_app(tmp_path)
    csrf_guard = next(middleware for middleware in app.middlewares if middleware.__name__ == "csrf_guard_mutating_api")
    request = make_mocked_request(
        "POST",
        "/api/_origin_probe",
        headers={"Host": authority, "Sec-Fetch-Site": "same-origin"},
        app=app,
        transport=_LoopbackTransport(),
    )

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    with pytest.raises(web.HTTPForbidden):
        await csrf_guard(request, handler)


@pytest.mark.asyncio
async def test_remote_mode_keeps_token_auth_for_nonlocal_host_authorities(tmp_path: Path) -> None:
    app = await _build_app(tmp_path, access_mode="remote")
    guard = app[APP_REQUIRE_API_ACCESS]
    request = make_mocked_request(
        "GET",
        "/api/_host_probe",
        headers={"Host": "remote.example", "Authorization": "Bearer remote-secret"},
        app=app,
        transport=_LoopbackTransport(),
    )
    guard(request)
