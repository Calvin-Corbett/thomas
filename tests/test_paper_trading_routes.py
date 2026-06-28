"""HTTP-surface tests for the Paper Trading routes.

Drives the real aiohttp handlers through an in-process TestServer (no full app
boot, no network). Proves the human-approval gate holds at the HTTP boundary:
a proposal cannot be submitted until the authenticated owner approves it.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import load_config
from thomas.server.app_keys import APP_CONFIG, APP_LOCAL_STEP_UP_AUTH_PROVIDER
from thomas.server.routes.paper_trading_aiohttp import register_paper_trading_routes


class _AuthResult:
    def __init__(self, authorized):
        self.authorized = authorized
        self.method = "test"
        self.platform = "test"
        self.error_code = None if authorized else "auth_denied"


class _AllowAuth:
    def authorize(self, action, reason):
        return _AuthResult(True)


class _DenyAuth:
    def authorize(self, action, reason):
        return _AuthResult(False)


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_PAPER_TRADING_DIR", str(tmp_path))
    for var in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # The plugin-enabled gate is orthogonal to this test; force it on.
    monkeypatch.setattr(
        "thomas.server.desktop_plugins.is_plugin_enabled",
        lambda cfg, pid: True,
        raising=False,
    )
    return tmp_path


def _make_app(tmp_path, provider="allow") -> web.Application:
    app = web.Application()
    cfg = load_config()
    cfg.memory.root = str(tmp_path)
    app[APP_CONFIG] = cfg
    if provider == "allow":
        app[APP_LOCAL_STEP_UP_AUTH_PROVIDER] = _AllowAuth()
    elif provider == "deny":
        app[APP_LOCAL_STEP_UP_AUTH_PROVIDER] = _DenyAuth()
    # provider == "none": leave the step-up provider unset (fail-closed case)
    register_paper_trading_routes(app, require_api_access=lambda request: None)
    return app


async def _drive(tmp_path, scenario, provider="allow"):
    server = TestServer(_make_app(tmp_path, provider))
    client = TestClient(server)
    await client.start_server()
    try:
        return await scenario(client)
    finally:
        await client.close()


async def _create_pending(client):
    create = await client.post(
        "/api/plugins/paper-trading/proposals",
        json={
            "symbol": "AAPL",
            "side": "buy",
            "notional": 300,
            "thesis": "t",
            "invalidation": "i",
        },
    )
    return (await create.json())["id"]


def test_bootstrap_reports_simulator(clean_env, tmp_path):
    async def scenario(client):
        resp = await client.get("/api/plugins/paper-trading/bootstrap")
        assert resp.status == 200
        body = await resp.json()
        assert body["simulated"] is True
        assert body["has_credentials"] is False
        assert "risk_rules" in body
        return body

    asyncio.run(_drive(tmp_path, scenario))


def test_propose_then_approve_and_submit_via_http(clean_env, tmp_path):
    async def scenario(client):
        create = await client.post(
            "/api/plugins/paper-trading/proposals",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "notional": 400,
                "thesis": "breakout",
                "invalidation": "loses the level",
            },
        )
        assert create.status == 201
        proposal = await create.json()
        assert proposal["status"] == "pending_approval"
        pid = proposal["id"]

        approve = await client.post(
            f"/api/plugins/paper-trading/proposals/{pid}/approve",
            json={"submit": True},
        )
        assert approve.status == 200
        approved = await approve.json()
        assert approved["status"] in ("submitted", "filled")
        assert approved["broker_order_id"]
        return approved

    asyncio.run(_drive(tmp_path, scenario))


def test_submit_without_approval_blocked_at_http(clean_env, tmp_path):
    async def scenario(client):
        create = await client.post(
            "/api/plugins/paper-trading/proposals",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "notional": 400,
                "thesis": "t",
                "invalidation": "i",
            },
        )
        proposal = await create.json()
        pid = proposal["id"]
        # Attempt to submit WITHOUT approving -> must be rejected (409 Conflict).
        submit = await client.post(f"/api/plugins/paper-trading/proposals/{pid}/submit")
        assert submit.status == 409
        return submit.status

    asyncio.run(_drive(tmp_path, scenario))


def test_create_proposal_requires_thesis(clean_env, tmp_path):
    async def scenario(client):
        resp = await client.post(
            "/api/plugins/paper-trading/proposals",
            json={"symbol": "AAPL", "side": "buy", "notional": 400},
        )
        assert resp.status == 400
        return resp.status

    asyncio.run(_drive(tmp_path, scenario))


def test_approve_denied_when_human_auth_denied(clean_env, tmp_path):
    async def scenario(client):
        pid = await _create_pending(client)
        approve = await client.post(
            f"/api/plugins/paper-trading/proposals/{pid}/approve",
            json={"submit": True},
        )
        assert approve.status == 403
        # The proposal must remain unapproved/unsubmitted.
        lst = await client.get("/api/plugins/paper-trading/proposals")
        rows = await lst.json()
        row = next(r for r in rows if r["id"] == pid)
        assert row["status"] == "pending_approval"

    asyncio.run(_drive(tmp_path, scenario, provider="deny"))


def test_approve_blocked_when_no_provider_available(clean_env, tmp_path, monkeypatch):
    # No app-key provider AND the on-demand builder yields nothing -> fail closed.
    monkeypatch.setattr(
        "thomas.server.routes.paper_trading_aiohttp._default_step_up_provider",
        lambda: None,
    )

    async def scenario(client):
        pid = await _create_pending(client)
        approve = await client.post(
            f"/api/plugins/paper-trading/proposals/{pid}/approve",
            json={"submit": True},
        )
        assert approve.status == 403

    asyncio.run(_drive(tmp_path, scenario, provider="none"))


def test_approve_uses_on_demand_provider_when_app_key_absent(clean_env, tmp_path, monkeypatch):
    # The fix for the fix-verification finding: even with NO provider installed
    # at boot (app key absent), the gate builds one on demand. Here we stub that
    # builder to an allowing provider and confirm approval then succeeds.
    monkeypatch.setattr(
        "thomas.server.routes.paper_trading_aiohttp._default_step_up_provider",
        lambda: _AllowAuth(),
    )

    async def scenario(client):
        pid = await _create_pending(client)
        approve = await client.post(
            f"/api/plugins/paper-trading/proposals/{pid}/approve",
            json={"submit": True},
        )
        assert approve.status == 200
        body = await approve.json()
        assert body["status"] in ("submitted", "filled")

    asyncio.run(_drive(tmp_path, scenario, provider="none"))


def test_invalid_symbol_rejected_at_http(clean_env, tmp_path):
    async def scenario(client):
        resp = await client.post(
            "/api/plugins/paper-trading/proposals",
            json={
                "symbol": "<script>",
                "side": "buy",
                "notional": 200,
                "thesis": "t",
                "invalidation": "i",
            },
        )
        assert resp.status == 400

    asyncio.run(_drive(tmp_path, scenario))
