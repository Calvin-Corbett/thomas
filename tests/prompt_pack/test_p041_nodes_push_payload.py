import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import pytest
from aiohttp import web


# When this test file is executed in isolation, pytest may choose a rootdir that
# does not include the project root on sys.path. Ensure imports resolve.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def _start_server(app: web.Application) -> tuple[str, Callable[[], Awaitable[None]]]:
    """Start an aiohttp server bound to an ephemeral port (async version)."""

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    sockets = getattr(site, "_server", None).sockets  # type: ignore[attr-defined]
    port = sockets[0].getsockname()[1]

    async def _cleanup() -> None:
        await runner.cleanup()

    return f"http://127.0.0.1:{port}", _cleanup


def _start_server_in_thread(app: web.Application) -> Tuple[str, Callable[[], None]]:
    """Start an aiohttp server in a background thread for sync tests.

    This avoids calling asyncio.run() from within pytest-asyncio event loops.
    """

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: Dict[str, Any] = {}

    def _run() -> None:
        asyncio.set_event_loop(loop)

        async def _start() -> None:
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()

            sockets = getattr(site, "_server", None).sockets  # type: ignore[attr-defined]
            port = sockets[0].getsockname()[1]
            state.update({"runner": runner, "port": port})
            ready.set()

        loop.run_until_complete(_start())
        loop.run_forever()

        runner: web.AppRunner = state["runner"]
        loop.run_until_complete(runner.cleanup())
        loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    ready.wait(timeout=5)
    if not ready.is_set():
        raise RuntimeError("server thread did not start")

    base_url = f"http://127.0.0.1:{state['port']}"

    def _stop() -> None:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)

    return base_url, _stop


@pytest.mark.asyncio
async def test_push_payload_success() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadRequest, push_payload_to_nodes

    received: Dict[str, Any] = {}

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        received.update(body)
        return web.json_response({"received": body})

    app = web.Application()
    app.router.add_post("/payload", handler)
    base_url, cleanup = await _start_server(app)
    try:
        req = NodesPushPayloadRequest(nodes=[base_url], payload={"hello": "world"}, endpoint_path="/payload")
        resp = await push_payload_to_nodes(req)
        d = resp.to_dict()

        assert d["ok"] is True
        assert d["pushed"] == 1
        assert d["failed"] == 0
        assert d["results"][0]["ok"] is True
        assert d["results"][0]["status"] == 200
        assert received == {"hello": "world"}
        assert d["results"][0]["response_json"] == {"received": {"hello": "world"}}
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_push_payload_remote_error_captured() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadRequest, push_payload_to_nodes

    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="boom")

    app = web.Application()
    app.router.add_post("/payload", handler)
    base_url, cleanup = await _start_server(app)
    try:
        req = NodesPushPayloadRequest(nodes=[base_url], payload={"x": 1}, endpoint_path="/payload")
        resp = await push_payload_to_nodes(req)
        d = resp.to_dict()

        assert d["ok"] is False
        assert d["failed"] == 1
        r0 = d["results"][0]
        assert r0["ok"] is False
        assert r0["status"] == 500
        assert r0["error_code"] == "remote_error"
        assert "boom" in (r0["error"] or "")
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_node_id_resolution_via_node_map() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadRequest, push_payload_to_nodes

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response({"ok": True, "body": body})

    app = web.Application()
    app.router.add_post("/payload", handler)
    base_url, cleanup = await _start_server(app)
    try:
        req = NodesPushPayloadRequest(
            nodes=["node-1"],
            payload={"a": 1},
            node_endpoints={"node-1": base_url},
        )
        resp = await push_payload_to_nodes(req)
        d = resp.to_dict()
        assert d["ok"] is True
        assert d["results"][0]["url"] == base_url + "/payload"
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_full_url_with_non_root_path_is_not_appended() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadRequest, push_payload_to_nodes

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"path": request.path})

    app = web.Application()
    app.router.add_post("/custom", handler)
    base_url, cleanup = await _start_server(app)
    try:
        full = base_url + "/custom"
        req = NodesPushPayloadRequest(nodes=[full], payload={"x": 1}, endpoint_path="/payload")
        resp = await push_payload_to_nodes(req)
        d = resp.to_dict()
        assert d["ok"] is True
        assert d["results"][0]["url"] == full
        assert d["results"][0]["response_json"] == {"path": "/custom"}
    finally:
        await cleanup()


def test_push_payload_invalid_payload_raises() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadError, NodesPushPayloadRequest, push_payload_to_nodes_sync

    req = NodesPushPayloadRequest(nodes=["http://example.invalid"], payload={"bad": {1, 2, 3}})
    with pytest.raises(NodesPushPayloadError) as ei:
        push_payload_to_nodes_sync(req)
    assert ei.value.code == "invalid_input"


@pytest.mark.asyncio
async def test_push_payload_missing_node_map_raises() -> None:
    from thomas.nodes.p041_nodes_push_payload import NodesPushPayloadError, NodesPushPayloadRequest, push_payload_to_nodes

    req = NodesPushPayloadRequest(nodes=["node-1"], payload={"x": 1})
    with pytest.raises(NodesPushPayloadError) as ei:
        await push_payload_to_nodes(req)
    assert ei.value.code == "missing_config"


def test_cli_json_success(capsys: pytest.CaptureFixture[str]) -> None:
    # Spin up a server in a thread so we can run the CLI's sync runner.
    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response({"received": body})

    app = web.Application()
    app.router.add_post("/payload", handler)
    base_url, stop = _start_server_in_thread(app)
    try:
        from thomas.cli.commands.nodes.p041_nodes_push_payload import run

        rc = run([
            "--node",
            base_url,
            "--payload",
            '{"hello":"world"}',
            "--json",
        ])
        assert rc == 0

        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["ok"] is True
        assert data["pushed"] == 1
        assert data["failed"] == 0
        assert data["results"][0]["ok"] is True
    finally:
        stop()


def test_cli_json_invalid_payload(capsys: pytest.CaptureFixture[str]) -> None:
    from thomas.cli.commands.nodes.p041_nodes_push_payload import run

    rc = run([
        "--node",
        "http://example.invalid",
        "--payload",
        "not-json",
        "--json",
    ])
    assert rc == 2

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_input"


def test_cli_exit_code_1_on_remote_failure() -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="nope")

    app = web.Application()
    app.router.add_post("/payload", handler)
    base_url, stop = _start_server_in_thread(app)
    try:
        from thomas.cli.commands.nodes.p041_nodes_push_payload import run

        rc = run([
            "--node",
            base_url,
            "--payload",
            '{"x":1}',
            "--json",
        ])
        assert rc == 1
    finally:
        stop()
