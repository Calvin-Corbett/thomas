from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.tools import browser as mod


@pytest.mark.asyncio
async def test_browser_click_tool_honors_post_click_stabilize_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {"stabilize_ms": None}

    class _FakeLocator:
        async def wait_for(self, **kwargs):
            return None

        async def scroll_into_view_if_needed(self, **kwargs):
            return None

        async def click(self, **kwargs):
            return None

    class _FakePage:
        url = "https://open-claw.org/"

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url="https://open-claw.org/")
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "action-direct"
        assert lane == "action"
        return fake_session, fake_page

    async def _fake_resolve_locator(page, selector: str):
        _ = page
        assert selector == 'role=link[name="Docs"]'
        return _FakeLocator()

    async def _fake_stabilize(page, *, max_ms: int = 3000) -> None:
        _ = page
        seen["stabilize_ms"] = max_ms

    async def _fake_rehydrate(sess, page):
        _ = sess, page
        return None

    def _fake_ensure_navigated(page):
        _ = page
        return None

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)
    monkeypatch.setattr(mod, "_resolve_locator_for_click", _fake_resolve_locator)
    monkeypatch.setattr(mod, "_best_effort_stabilize", _fake_stabilize)
    monkeypatch.setattr(mod, "_rehydrate_if_needed", _fake_rehydrate)
    monkeypatch.setattr(mod, "_ensure_navigated", _fake_ensure_navigated)

    result = await mod.BrowserClickTool().execute(
        {
            "selector": 'role=link[name="Docs"]',
            "session": "action-direct",
            "timeout_ms": 1500,
            "post_click_stabilize_ms": 800,
        }
    )

    assert result.ok is True
    assert seen["stabilize_ms"] == 800


@pytest.mark.asyncio
async def test_browser_click_tool_prefers_direct_link_navigation_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {"goto": None, "clicked": False, "stabilize_ms": None}

    class _FakeLocator:
        async def wait_for(self, **kwargs):
            return None

        async def get_attribute(self, name: str) -> str | None:
            assert name == "href"
            return "/docs"

        async def scroll_into_view_if_needed(self, **kwargs):
            raise AssertionError("direct link navigation should skip scrolling")

        async def click(self, **kwargs):
            seen["clicked"] = True
            return None

    class _FakePage:
        url = "https://open-claw.org/"

        async def goto(self, url: str, **kwargs):
            seen["goto"] = {"url": url, **kwargs}
            self.url = url
            return SimpleNamespace(status=200)

        async def wait_for_load_state(self, state: str, **kwargs):
            assert state == "domcontentloaded"
            return None

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url="https://open-claw.org/")
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "action-direct"
        assert lane == "action"
        return fake_session, fake_page

    async def _fake_resolve_locator(page, selector: str):
        _ = page
        assert selector == 'role=link[name="Docs"]'
        return _FakeLocator()

    async def _fake_stabilize(page, *, max_ms: int = 3000) -> None:
        _ = page
        seen["stabilize_ms"] = max_ms

    async def _fake_rehydrate(sess, page):
        _ = sess, page
        return None

    def _fake_ensure_navigated(page):
        _ = page
        return None

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)
    monkeypatch.setattr(mod, "_resolve_locator_for_click", _fake_resolve_locator)
    monkeypatch.setattr(mod, "_best_effort_stabilize", _fake_stabilize)
    monkeypatch.setattr(mod, "_rehydrate_if_needed", _fake_rehydrate)
    monkeypatch.setattr(mod, "_ensure_navigated", _fake_ensure_navigated)

    result = await mod.BrowserClickTool().execute(
        {
            "selector": 'role=link[name="Docs"]',
            "session": "action-direct",
            "timeout_ms": 1500,
            "post_click_stabilize_ms": 800,
            "prefer_link_navigation": True,
        }
    )

    assert result.ok is True
    assert seen["clicked"] is False
    assert seen["goto"] == {"url": "https://open-claw.org/docs", "wait_until": "commit", "timeout": 1500}
    assert seen["stabilize_ms"] == 250
