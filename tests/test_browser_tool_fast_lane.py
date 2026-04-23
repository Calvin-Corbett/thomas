from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.tools import browser as mod


def test_browser_launch_kwargs_prefers_env_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    browser_path = tmp_path / "custom-browser.exe"
    browser_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("THOMAS_BROWSER_EXECUTABLE", str(browser_path))

    kwargs = mod._browser_launch_kwargs(headless=True)

    assert kwargs["headless"] is True
    assert kwargs["executable_path"] == str(browser_path)


def test_browser_launch_kwargs_prefers_known_installed_browser(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    browser_path = tmp_path / "msedge.exe"
    browser_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("THOMAS_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr(mod, "_PREFERRED_BROWSER_EXECUTABLES", (str(browser_path),))

    kwargs = mod._browser_launch_kwargs(headless=False)

    assert kwargs == {"headless": False, "executable_path": str(browser_path)}


def test_browser_context_kwargs_ignore_https_errors() -> None:
    assert mod._browser_context_kwargs() == {"ignore_https_errors": True}


def test_same_target_url_ignores_trailing_slash_and_case() -> None:
    assert mod._same_target_url("https://Open-Claw.org/", "https://open-claw.org") is True
    assert mod._same_target_url("https://open-claw.org/docs", "https://open-claw.org") is False


@pytest.mark.asyncio
async def test_browser_open_tool_returns_headline(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeLocator:
        @property
        def first(self) -> _FakeLocator:
            return self

        async def text_content(self) -> str:
            return "OpenClaw: The AI that actually does things"

    class _FakePage:
        url = "about:blank"

        async def goto(self, *args, **kwargs):
            return SimpleNamespace(status=200)

        async def title(self) -> str:
            return "OpenClaw | The Open-Source Personal AI Assistant & Autonomous Agent"

        def locator(self, selector: str) -> _FakeLocator:
            assert selector == "h1"
            return _FakeLocator()

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url=None)
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "headline-test"
        assert headless is True
        assert lane == "action"
        return fake_session, fake_page

    async def _fake_stabilize(page, *, max_ms: int = 3000) -> None:
        return None

    async def _fake_extract_best_text(page) -> str:
        return "OpenClaw body copy"

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)
    monkeypatch.setattr(mod, "_best_effort_stabilize", _fake_stabilize)
    monkeypatch.setattr(mod, "_extract_best_text", _fake_extract_best_text)

    result = await mod.BrowserOpenTool().execute(
        {"url": "https://open-claw.org", "session": "headline-test", "headless": True}
    )

    assert result.ok is True
    assert result.error is None
    assert result.data["headline"] == "OpenClaw: The AI that actually does things"
    assert result.data["title"] == "OpenClaw | The Open-Source Personal AI Assistant & Autonomous Agent"
    assert result.data["text"] == "OpenClaw body copy"


@pytest.mark.asyncio
async def test_browser_open_tool_headline_only_skips_heavy_text_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"stabilize": 0, "extract": 0}
    seen = {"wait_until": None}

    class _FakeLocator:
        @property
        def first(self) -> _FakeLocator:
            return self

        async def text_content(self) -> str:
            return "OpenClaw: The AI that actually does things"

    class _FakePage:
        url = "about:blank"

        async def goto(self, *args, **kwargs):
            seen["wait_until"] = kwargs.get("wait_until")
            return SimpleNamespace(status=200)

        async def title(self) -> str:
            return "OpenClaw | The Open-Source Personal AI Assistant & Autonomous Agent"

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def wait_for_load_state(self, *args, **kwargs):
            return None

        def locator(self, selector: str) -> _FakeLocator:
            assert selector == "h1"
            return _FakeLocator()

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url=None)
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "headline-fast"
        assert headless is True
        assert lane == "read"
        return fake_session, fake_page

    async def _fake_stabilize(page, *, max_ms: int = 3000) -> None:
        _ = page, max_ms
        calls["stabilize"] += 1

    async def _fake_extract_best_text(page) -> str:
        _ = page
        calls["extract"] += 1
        return "OpenClaw body copy"

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)
    monkeypatch.setattr(mod, "_best_effort_stabilize", _fake_stabilize)
    monkeypatch.setattr(mod, "_extract_best_text", _fake_extract_best_text)

    result = await mod.BrowserOpenTool().execute(
        {"url": "https://open-claw.org", "session": "headline-fast", "headless": True, "headline_only": True}
    )

    assert result.ok is True
    assert result.error is None
    assert result.data["headline"] == "OpenClaw: The AI that actually does things"
    assert result.data["text"] == ""
    assert seen["wait_until"] == "commit"
    assert calls["stabilize"] == 0
    assert calls["extract"] == 0


@pytest.mark.asyncio
async def test_browser_open_tool_navigation_only_skips_metadata_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {"wait_until": None, "title_calls": 0, "selector_waits": 0}

    class _FakePage:
        url = "about:blank"

        async def goto(self, *args, **kwargs):
            seen["wait_until"] = kwargs.get("wait_until")
            self.url = "https://open-claw.org/"
            return SimpleNamespace(status=200)

        async def title(self) -> str:
            seen["title_calls"] += 1
            return "OpenClaw"

        async def wait_for_selector(self, *args, **kwargs):
            seen["selector_waits"] += 1
            return None

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url=None)
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "action-direct"
        assert headless is True
        assert lane == "action"
        return fake_session, fake_page

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)

    result = await mod.BrowserOpenTool().execute(
        {
            "url": "https://open-claw.org",
            "session": "action-direct",
            "headless": True,
            "lane": "action",
            "headline_only": True,
            "navigation_only": True,
        }
    )

    assert result.ok is True
    assert result.error is None
    assert result.data == {"url": "https://open-claw.org/", "title": "", "headline": "", "text": ""}
    assert seen["wait_until"] == "commit"
    assert seen["title_calls"] == 0
    assert seen["selector_waits"] == 0


@pytest.mark.asyncio
async def test_browser_open_tool_read_lane_uses_commit_navigation_for_main_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"read_stabilize": 0, "extract": 0, "load_state": 0}
    seen = {"wait_until": None}

    class _FakeLocator:
        @property
        def first(self) -> _FakeLocator:
            return self

        async def text_content(self) -> str:
            return "OpenClaw: The AI that actually does things"

    class _FakePage:
        url = "about:blank"

        async def goto(self, *args, **kwargs):
            seen["wait_until"] = kwargs.get("wait_until")
            return SimpleNamespace(status=200)

        async def title(self) -> str:
            return "OpenClaw | The Open-Source Personal AI Assistant & Autonomous Agent"

        async def wait_for_load_state(self, *args, **kwargs):
            calls["load_state"] += 1
            return None

        def locator(self, selector: str) -> _FakeLocator:
            assert selector == "h1"
            return _FakeLocator()

    fake_session = SimpleNamespace(lock=asyncio.Lock(), last_url=None)
    fake_page = _FakePage()

    async def _fake_ensure_session_page(session_name: str, *, headless: bool | None = None, lane: str = "action"):
        assert session_name == "content-fast"
        assert headless is True
        assert lane == "read"
        return fake_session, fake_page

    async def _fake_read_stabilize(page, *, settle_ms: int = 200) -> None:
        _ = page
        calls["read_stabilize"] += 1
        assert settle_ms == 200

    async def _fake_extract_best_text(page) -> str:
        _ = page
        calls["extract"] += 1
        return "OpenClaw body copy"

    monkeypatch.setattr(mod, "_ensure_session_page", _fake_ensure_session_page)
    monkeypatch.setattr(mod, "_best_effort_read_stabilize", _fake_read_stabilize)
    monkeypatch.setattr(mod, "_extract_best_text", _fake_extract_best_text)

    result = await mod.BrowserOpenTool().execute(
        {"url": "https://open-claw.org", "session": "content-fast", "headless": True, "lane": "read"}
    )

    assert result.ok is True
    assert result.error is None
    assert result.data["headline"] == "OpenClaw: The AI that actually does things"
    assert result.data["text"] == "OpenClaw body copy"
    assert seen["wait_until"] == "commit"
    assert calls["load_state"] == 1
    assert calls["read_stabilize"] == 1
    assert calls["extract"] == 1
