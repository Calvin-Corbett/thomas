import json
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import thomas.server.routes.gateway.p126_gateway_start_command as gateway_start_mod
from thomas.cli.commands.gateway import p126_gateway_start_command as gateway_cli_mod


def _write_json_config(path: Path, command):
    path.write_text(json.dumps({"command": command}), encoding="utf-8")
    return path


def _terminate_proc(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def test_start_gateway_process_success_and_idempotent(tmp_path: Path):
    cfg_path = _write_json_config(
        tmp_path / "gateway.json",
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    state = {}
    outcome1 = gateway_start_mod.start_gateway_process(state=state, config_path=str(cfg_path))
    assert outcome1.status == "started"
    assert isinstance(outcome1.pid, int) and outcome1.pid > 0

    outcome2 = gateway_start_mod.start_gateway_process(state=state, config_path=str(cfg_path))
    assert outcome2.status == "already_running"
    assert outcome2.pid == outcome1.pid

    _terminate_proc(state.get(gateway_start_mod.GATEWAY_PROCESS_KEY))


def test_cli_gateway_start_json_payload(tmp_path: Path):
    cfg_path = _write_json_config(
        tmp_path / "gateway_cli.json",
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    payload = gateway_cli_mod.run_gateway_start(
        gateway_cli_mod.GatewayStartCliOptions(config_path=str(cfg_path))
    )
    assert payload["ok"] is True
    assert payload["status"] in ("started", "already_running")
    assert isinstance(payload["pid"], int) and payload["pid"] > 0

    proc = gateway_cli_mod._CLI_STATE.get(gateway_start_mod.GATEWAY_PROCESS_KEY)
    _terminate_proc(proc)


@pytest.mark.asyncio
async def test_gateway_start_route_success_and_idempotent(tmp_path: Path):
    cfg_path = _write_json_config(
        tmp_path / "gateway_route.json",
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    app = web.Application()
    gateway_start_mod.register(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.post("/v1/gateway/start", json={"config_path": str(cfg_path)})
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        assert payload["status"] == "started"
        assert isinstance(payload["pid"], int) and payload["pid"] > 0

        resp2 = await client.post("/v1/gateway/start", json={"config_path": str(cfg_path)})
        assert resp2.status == 200
        payload2 = await resp2.json()
        assert payload2["ok"] is True
        assert payload2["status"] == "already_running"
        assert payload2["pid"] == payload["pid"]
    finally:
        _terminate_proc(gateway_start_mod.get_gateway_process(app))
        await client.close()


@pytest.mark.asyncio
async def test_gateway_start_route_missing_config_file(tmp_path: Path):
    missing = tmp_path / "nope.json"

    app = web.Application()
    gateway_start_mod.register(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.post("/v1/gateway/start", json={"config_path": str(missing)})
        assert resp.status == 400
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["type"] == "missing_config"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_start_route_missing_config_path_and_env(tmp_path: Path):
    app = web.Application()
    gateway_start_mod.register(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    old = os.environ.pop("THOMAS_GATEWAY_CONFIG", None)
    try:
        resp = await client.post("/v1/gateway/start", json={})
        assert resp.status == 400
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["type"] == "missing_config"
    finally:
        if old is not None:
            os.environ["THOMAS_GATEWAY_CONFIG"] = old
        await client.close()


@pytest.mark.asyncio
async def test_gateway_start_route_invalid_json_body(tmp_path: Path):
    app = web.Application()
    gateway_start_mod.register(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.post(
            "/v1/gateway/start",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["type"] == "invalid_input"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_start_route_external_failure_executable_missing(tmp_path: Path):
    cfg_path = _write_json_config(
        tmp_path / "bad_gateway.json",
        ["definitely-not-a-real-executable-xyz", "--version"],
    )

    app = web.Application()
    gateway_start_mod.register(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.post("/v1/gateway/start", json={"config_path": str(cfg_path)})
        assert resp.status == 502
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["error"]["type"] == "external_failure"
    finally:
        await client.close()
