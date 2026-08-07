from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.office_state import OfficeStateStore
from thomas.server.routes.office_state_aiohttp import register_office_state_routes


@pytest.mark.asyncio
async def test_office_state_api_persists_authoritative_follow_target(tmp_path: Path) -> None:
    app = web.Application()

    async def _read_json(request: web.Request):
        return await request.json()

    register_office_state_routes(
        app,
        root=tmp_path,
        require_api_access=lambda _request: None,
        read_json=_read_json,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        updated = await client.patch(
            "/api/office/state",
            json={"follow_agent_id": "agent-7"},
            headers={"X-User-Id": "owner"},
        )
        assert updated.status == 200
        assert (await updated.json())["state"]["follow_agent_id"] == "agent-7"
        loaded = await client.get("/api/office/state", headers={"X-User-Id": "owner"})
        assert (await loaded.json())["state"]["follow_agent_id"] == "agent-7"
        assert OfficeStateStore(tmp_path).get(user_id="owner")["follow_agent_id"] == "agent-7"
    finally:
        await client.close()


def test_office_bridge_declares_reload_and_live_iframe_refresh_contract() -> None:
    root = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"
    loader = (root / "app_runtime_loader.js").read_text(encoding="utf-8")
    bridge = (root / "runtime" / "office_server_state.js").read_text(encoding="utf-8")
    transport = (root / "workspace_chat_transport.js").read_text(encoding="utf-8")
    assert "'office_server_state.js'" in loader
    assert "fetch('/api/office/state', { cache: 'no-store' })" in bridge
    assert "event.origin !== location.origin" in bridge
    assert "event.data.type !== 'thomas:office-state:refresh'" in bridge
    assert "frame.contentWindow.postMessage(refresh, location.origin)" in transport


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="playwright not installed")
def test_office_iframe_message_applies_server_follow_state_without_reload() -> None:
    from playwright.sync_api import sync_playwright

    script = (
        Path(__file__).resolve().parents[1]
        / "thomas"
        / "server"
        / "web"
        / "js"
        / "runtime"
        / "office_server_state.js"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "http://thomas.test/",
            lambda route: route.fulfill(status=200, content_type="text/html", body="<main>Office</main>"),
        )
        page.goto("http://thomas.test/")
        page.evaluate(
            """() => {
              window.__serverAgent = 'agent-2';
              window.officeState = { followAgentId: '' };
              window.safeString = value => String(value || '').trim();
              window.officeSetFollowMode = (enabled, id) => { officeState.followAgentId = enabled ? id : ''; };
              window.officePersistCameraState = () => {};
              window.officeRenderScene = () => {};
              window.fetch = async () => ({ ok: true, json: async () => ({ state: { follow_agent_id: window.__serverAgent } }) });
            }"""
        )
        page.add_script_tag(path=str(script))
        page.wait_for_function("officeState.followAgentId === 'agent-2'")
        page.evaluate(
            """() => {
              window.__serverAgent = 'agent-9';
              window.postMessage({ type: 'thomas:office-state:refresh' }, location.origin);
            }"""
        )
        page.wait_for_function("officeState.followAgentId === 'agent-9'")
        assert page.url == "http://thomas.test/"
        browser.close()
