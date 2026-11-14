"""A Playwright that records what was launched and closed, and a server to run it on, for the browser row's tests.

A real Chromium is not what is under test: the row either asks for it to be closed or it does not. By hand the same was
done with a real one: one process before Stop, none after, and none after the server closed. ``hang_on_close`` makes the
browser's close wait for ever, and ``hang_on_goto`` makes a page's navigation wait until its page is closed and then fail
as a closed page does, so a test can press Stop now on a close that is stuck, or cut a call off partway.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.tools import browser, browser_parity

NAMES = {
    f"browser.{name}" for name in ("open", "click", "type", "screenshot", "extract", "close", "console", "network")
}


class World:
    """Everything the fake Playwright made, in order, so a test can see what was closed and what was launched."""

    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.browsers: list[Any] = []
        self.contexts: list[Any] = []
        self.pages: list[Any] = []
        self.headless: list[bool] = []
        self.hang_on_close = False
        self.hang_on_goto = False
        self.close_began = False

    def async_playwright(self) -> Any:
        async def start() -> Any:
            started = _Playwright(self)
            self.starts.append(started)
            return started

        return SimpleNamespace(start=start)


class _Closable:
    def __init__(self, world: World) -> None:
        self.world = world
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Page(_Closable):
    url = "about:blank"

    def is_closed(self) -> bool:
        return self.closed

    def set_default_navigation_timeout(self, _ms: int) -> None:
        pass

    def set_default_timeout(self, _ms: int) -> None:
        pass

    async def goto(self, url: str, **_options: Any) -> Any:
        if self.world.hang_on_goto:
            while not self.closed:
                await asyncio.sleep(0.01)
            raise RuntimeError("Target page, context or browser has been closed")
        self.url = url
        return None

    async def close(self) -> None:
        self.closed = True


class _Context(_Closable):
    async def new_page(self) -> _Page:
        page = _Page(self.world)
        self.world.pages.append(page)
        return page


class _Browser(_Closable):
    def is_connected(self) -> bool:
        return not self.closed

    async def new_context(self) -> _Context:
        context = _Context(self.world)
        self.world.contexts.append(context)
        return context

    async def close(self) -> None:
        self.world.close_began = True
        while self.world.hang_on_close:
            await asyncio.sleep(0.01)
        self.closed = True


class _Playwright:
    def __init__(self, world: World) -> None:
        self.stopped = False
        self.chromium = SimpleNamespace(launch=self._launch)
        self._world = world

    async def _launch(self, headless: bool = True) -> _Browser:
        made = _Browser(self._world)
        self._world.browsers.append(made)
        self._world.headless.append(headless)
        return made

    async def stop(self) -> None:
        self.stopped = True


def install(monkeypatch: pytest.MonkeyPatch) -> World:
    """Put a fake Playwright under ``thomas.tools.browser`` with a clean session state, until the test ends."""
    made = World()
    monkeypatch.setattr(browser, "_STATE", browser._BrowserState())
    monkeypatch.setattr(browser, "_PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(browser, "async_playwright", made.async_playwright, raising=False)
    monkeypatch.setattr(browser_parity, "_TELEMETRY", {})
    return made


def on_a_server(tmp_path: Path, scenario: Callable[[TestClient, Any], Any]) -> None:
    """Run ``scenario(client, app)`` on a real server once every row has started. Closing it stops every row."""

    async def run() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            await scenario(client, app)

    asyncio.run(run())


async def press(client: TestClient, app: Any, way: str) -> None:
    assert (await client.post(f"/api/plugins/thomas/browser/{way}")).status == 200
    await views.rows_once_started(app[APP_RUNTIME_PLUGINS])


def state(app: Any) -> str:
    return views.state_of(app[APP_RUNTIME_PLUGINS], "browser")
