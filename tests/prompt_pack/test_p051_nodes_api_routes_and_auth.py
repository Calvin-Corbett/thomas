from __future__ import annotations

import argparse
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.cli.commands.nodes import p051_nodes_api_routes_and_auth as cli_mod
from thomas.marketplace.nodes import p051_nodes_api_routes_and_auth as nodes_api


def test_nodes_api_list_success_and_schema() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore(
            [nodes_api.NodeRecord(id="n1", label="Node 1", status="ready")]
        )

        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(
                "/api/nodes",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            assert body["count"] == 1
            assert body["nodes"][0]["id"] == "n1"

            resp = await client.get(
                "/api/nodes/schema",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            schema = body["schema"]
            assert schema["name"] == "nodes"
            paths = {r["path"] for r in schema["routes"]}
            assert "/api/nodes" in paths
            assert "/api/nodes/{node_id}" in paths
            assert "/api/nodes/schema" in paths
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_auth_missing_token_header() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore([])
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get("/api/nodes")
            assert resp.status == 401
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "missing_token"
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_auth_invalid_token() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore([])
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get("/api/nodes", headers={"Authorization": "Bearer wrong"})
            assert resp.status == 401
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "invalid_token"
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_auth_missing_config_is_deterministic() -> None:
    async def run() -> None:
        app = web.Application()
        # No token configured
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore([])
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get("/api/nodes", headers={"Authorization": "Bearer anything"})
            assert resp.status == 500
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "auth_not_configured"
            assert "token_env_vars" in body["error"]["details"]
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_invalid_node_id() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore([])
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(
                "/api/nodes/!!bad!!",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 400
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "invalid_input"
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_not_found() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = nodes_api.InMemoryNodeStore([])
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(
                "/api/nodes/nothere",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 404
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "not_found"
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_external_failure_missing_store() -> None:
    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        # No store configured
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(
                "/api/nodes",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 502
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "external_failure"
            assert body["error"]["details"].get("missing") is True
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_nodes_api_external_failure_store_raises() -> None:
    class BoomStore:
        async def list_nodes(self):
            raise RuntimeError("boom")

        async def get_node(self, node_id: str):
            raise RuntimeError("boom")

    async def run() -> None:
        app = web.Application()
        app[nodes_api.NODES_API_TOKEN_KEY] = "secret-token"
        app[nodes_api.NODE_STORE_KEY] = BoomStore()
        nodes_api.register(app, prefix="/api")

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(
                "/api/nodes",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status == 502
            body = await resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "external_failure"
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def test_cli_nodes_api_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Ensure --check-config fails deterministically when no env vars are set
    for key in nodes_api.DEFAULT_TOKEN_ENV_VARS:
        monkeypatch.delenv(key, raising=False)

    parser = argparse.ArgumentParser(prog="thomas nodes")
    sub = parser.add_subparsers(dest="cmd")
    cli_mod.register(sub)

    args = parser.parse_args(["api", "--json"])
    assert hasattr(args, "func")
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["schema"]["name"] == "nodes"

    args = parser.parse_args(["api", "--check-config", "--json"])
    rc = args.func(args)
    assert rc == 2
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth_not_configured"
