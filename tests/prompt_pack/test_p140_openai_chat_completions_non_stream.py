import pytest
from aiohttp import ClientSession, web
from typing import Tuple

from thomas.server.routes.gateway import p140_openai_chat_completions_non_stream as p140


async def _start_server(app: web.Application) -> Tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]
    return runner, f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_p140_success_pass_through_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def upstream_handler(request: web.Request) -> web.Response:
        payload = await request.json()
        assert payload.get("stream") is False
        return web.json_response(
            {
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 123,
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    upstream_app = web.Application()
    upstream_app.router.add_post("/v1/chat/completions", upstream_handler)
    upstream_runner, upstream_base = await _start_server(upstream_app)

    gateway_app = web.Application()
    p140.register(gateway_app)
    gateway_runner, gateway_base = await _start_server(gateway_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", upstream_base)

        async with ClientSession() as session:
            resp = await session.post(
                f"{gateway_base}/v1/chat/completions",
                json={"model": "gpt-test", "messages": [{"role": "user", "content": "ping"}]},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == "chatcmpl_test"
            assert data["choices"][0]["message"]["content"] == "pong"
    finally:
        await gateway_runner.cleanup()
        await upstream_runner.cleanup()


@pytest.mark.asyncio
async def test_p140_invalid_input_returns_openai_error(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_app = web.Application()
    p140.register(gateway_app)
    gateway_runner, gateway_base = await _start_server(gateway_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9")  # won't be reached due to validation error

        async with ClientSession() as session:
            resp = await session.post(f"{gateway_base}/v1/chat/completions", json={"messages": []})
            assert resp.status == 400
            data = await resp.json()
            assert "error" in data
            assert data["error"]["type"] == "invalid_request_error"
    finally:
        await gateway_runner.cleanup()


@pytest.mark.asyncio
async def test_p140_missing_config_returns_deterministic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_app = web.Application()
    p140.register(gateway_app)
    gateway_runner, gateway_base = await _start_server(gateway_app)

    try:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        async with ClientSession() as session:
            resp = await session.post(
                f"{gateway_base}/v1/chat/completions",
                json={"model": "gpt-test", "messages": [{"role": "user", "content": "ping"}]},
            )
            assert resp.status == 500
            data = await resp.json()
            assert data["error"]["code"] == "missing_openai_api_key"
    finally:
        await gateway_runner.cleanup()


@pytest.mark.asyncio
async def test_p140_upstream_non_json_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def upstream_handler(_: web.Request) -> web.Response:
        return web.Response(status=500, text="oops")

    upstream_app = web.Application()
    upstream_app.router.add_post("/v1/chat/completions", upstream_handler)
    upstream_runner, upstream_base = await _start_server(upstream_app)

    gateway_app = web.Application()
    p140.register(gateway_app)
    gateway_runner, gateway_base = await _start_server(gateway_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", upstream_base)

        async with ClientSession() as session:
            resp = await session.post(
                f"{gateway_base}/v1/chat/completions",
                json={"model": "gpt-test", "messages": [{"role": "user", "content": "ping"}]},
            )
            assert resp.status == 502
            data = await resp.json()
            assert data["error"]["code"] == "upstream_non_json_error"
    finally:
        await gateway_runner.cleanup()
        await upstream_runner.cleanup()


@pytest.mark.asyncio
async def test_p140_schema_endpoint() -> None:
    gateway_app = web.Application()
    p140.register(gateway_app)
    gateway_runner, gateway_base = await _start_server(gateway_app)

    try:
        async with ClientSession() as session:
            resp = await session.get(f"{gateway_base}{p140.THOMAS_SCHEMA_PATH}")
            assert resp.status == 200
            data = await resp.json()
            assert data["prompt_id"] == "p140"
            assert "request_schema" in data and "response_schema" in data
            assert data["paths"]["openai"] == p140.OPENAI_CHAT_COMPLETIONS_PATH
    finally:
        await gateway_runner.cleanup()
