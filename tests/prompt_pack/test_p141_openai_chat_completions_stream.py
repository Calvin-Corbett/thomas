import asyncio
import inspect
import json
from collections.abc import Callable, Iterable
from typing import Any

import pytest
from aiohttp import ClientSession, web


def _pick_app_factory() -> Callable[..., Any]:
    """Best-effort discovery of the Thomas aiohttp app factory.

    In the real Thomas repository, this imports ``thomas.server.app`` and
    locates an app factory (e.g. ``create_app``).

    In pared-down environments where the full Thomas server isn't present,
    we fall back to constructing a minimal aiohttp application and registering
    the P141 route module directly.
    """

    try:
        import thomas.server.app as app_mod  # type: ignore

        for name in [
            "create_app",
            "make_app",
            "build_app",
            "init_app",
            "get_app",
            "app",
        ]:
            fn = getattr(app_mod, name, None)
            if callable(fn):
                return fn

        raise RuntimeError("Could not find a Thomas app factory in thomas.server.app")
    except ModuleNotFoundError:
        from thomas.server.routes.gateway import p141_openai_chat_completions_stream as route_mod  # type: ignore

        def _fallback_app_factory(*_args: Any, **_kwargs: Any) -> web.Application:
            app = web.Application()
            if hasattr(route_mod, "register"):
                route_mod.register(app)  # type: ignore[attr-defined]
            elif hasattr(route_mod, "routes"):
                app.add_routes(route_mod.routes)  # type: ignore[attr-defined]
            return app

        return _fallback_app_factory


async def _make_thomas_app() -> web.Application:
    factory = _pick_app_factory()

    # Try a few call shapes.
    for args in [(), ([],), ({},)]:
        try:
            res = factory(*args)
        except TypeError:
            continue

        if inspect.isawaitable(res):
            res = await res

        if isinstance(res, web.Application):
            return res

    raise RuntimeError("Thomas app factory did not return an aiohttp.web.Application")


async def _start_app(app: web.Application) -> tuple[web.AppRunner, int]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    # Pull the allocated port from the underlying server socket.
    assert site._server is not None  # type: ignore[attr-defined]
    sockets = site._server.sockets  # type: ignore[attr-defined]
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, int(port)


async def _stop_app(runner: web.AppRunner) -> None:
    await runner.cleanup()


def _candidate_gateway_paths() -> Iterable[str]:
    # The route module registers multiple aliases; also allow for an API prefix
    # in case the Thomas app mounts routes under /api.
    base_paths = [
        "/gateway/p141/openai_chat_completions_stream",
        "/gateway/p141/openai-chat-completions-stream",
        "/gateway/openai/chat_completions/stream",
        "/gateway/openai/chat-completions/stream",
        "/gateway/openai/chat/completions/stream",
    ]
    for p in base_paths:
        yield p
        yield "/api" + p


async def _post_first_non_404(session: ClientSession, base_url: str, paths: Iterable[str], *, json_body: Any):
    for path in paths:
        resp = await session.post(base_url + path, json=json_body)
        if resp.status != 404:
            return resp, path
        resp.release()

    raise AssertionError("Gateway route not found (all candidate paths returned 404)")


def _make_upstream_app() -> web.Application:
    app = web.Application()

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        model = body.get("model")

        if model == "bad-model":
            return web.json_response({"error": {"message": "bad model"}}, status=400)

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        chunks = [
            {
                "id": "chatcmpl_test",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant"}}],
            },
            {
                "id": "chatcmpl_test",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": "Hello"}}],
            },
            {
                "id": "chatcmpl_test",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": " world"}}],
            },
        ]

        for c in chunks:
            await resp.write(f"data: {json.dumps(c)}\n\n".encode())
            await asyncio.sleep(0)

        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    app.router.add_post("/v1/chat/completions", chat_completions)
    return app


@pytest.mark.asyncio
async def test_p141_stream_success(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream_runner, upstream_port = await _start_app(_make_upstream_app())

    thomas_app = await _make_thomas_app()
    thomas_runner, thomas_port = await _start_app(thomas_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{upstream_port}/v1")

        async with ClientSession() as session:
            payload = {
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            }
            resp, used_path = await _post_first_non_404(
                session,
                f"http://127.0.0.1:{thomas_port}",
                _candidate_gateway_paths(),
                json_body=payload,
            )

            assert resp.status == 200, f"unexpected status via {used_path}: {resp.status}"
            assert "text/event-stream" in resp.headers.get("Content-Type", "")

            body = await resp.text()
            assert "data: [DONE]" in body
            assert "Hello" in body
            assert "world" in body

    finally:
        await _stop_app(thomas_runner)
        await _stop_app(upstream_runner)


@pytest.mark.asyncio
async def test_p141_invalid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # No upstream required for validation errors.
    thomas_app = await _make_thomas_app()
    thomas_runner, thomas_port = await _start_app(thomas_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")

        async with ClientSession() as session:
            payload = {"messages": [{"role": "user", "content": "hi"}]}
            resp, _ = await _post_first_non_404(
                session, f"http://127.0.0.1:{thomas_port}", _candidate_gateway_paths(), json_body=payload
            )
            assert resp.status == 400
            data = await resp.json(content_type=None)
            assert data["ok"] is False
            assert data["error"]["code"] == "invalid_request"

    finally:
        await _stop_app(thomas_runner)


@pytest.mark.asyncio
async def test_p141_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    thomas_app = await _make_thomas_app()
    thomas_runner, thomas_port = await _start_app(thomas_app)

    try:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")

        async with ClientSession() as session:
            payload = {
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            }
            resp, _ = await _post_first_non_404(
                session, f"http://127.0.0.1:{thomas_port}", _candidate_gateway_paths(), json_body=payload
            )
            assert resp.status == 500
            data = await resp.json(content_type=None)
            assert data["ok"] is False
            assert data["error"]["code"] == "missing_config"

    finally:
        await _stop_app(thomas_runner)


@pytest.mark.asyncio
async def test_p141_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream_runner, upstream_port = await _start_app(_make_upstream_app())

    thomas_app = await _make_thomas_app()
    thomas_runner, thomas_port = await _start_app(thomas_app)

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{upstream_port}/v1")

        async with ClientSession() as session:
            payload = {
                "model": "bad-model",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            }
            resp, _ = await _post_first_non_404(
                session, f"http://127.0.0.1:{thomas_port}", _candidate_gateway_paths(), json_body=payload
            )
            assert resp.status == 502
            data = await resp.json(content_type=None)
            assert data["ok"] is False
            assert data["error"]["code"] == "upstream_error"

    finally:
        await _stop_app(thomas_runner)
        await _stop_app(upstream_runner)
