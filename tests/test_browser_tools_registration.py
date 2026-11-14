"""Regression tests for browser-tool wiring into the live tool registry.

The 6 Playwright ``Tool`` subclasses in ``thomas/tools/browser.py`` were
defined but never registered into the agent/server ``ToolRegistry``
(wiring-audit finding browser-02 / tools-01). These tests lock in that they
are reachable through both the dedicated ``register_browser_tools`` helper and
the server's tool set when Playwright is installed. The server gets them from the
browser row (``thomas.server.rows.browser``), which lends them, so ``_build_tools``
on its own no longer carries them.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from thomas.tools.browser import TOOLS, register_browser_tools
from thomas.tools.registry import ToolRegistry

_EXPECTED_BROWSER_TOOLS = {
    "browser.open",
    "browser.click",
    "browser.type",
    "browser.screenshot",
    "browser.extract",
    "browser.close",
}

_PLAYWRIGHT_PRESENT = importlib.util.find_spec("playwright") is not None


def test_browser_tools_export_contract() -> None:
    """Every exported browser TOOL matches the ToolRegistry contract."""
    assert {t.name for t in TOOLS} == _EXPECTED_BROWSER_TOOLS
    for tool in TOOLS:
        # register() requires a truthy name; safe_execute awaits execute().
        assert tool.name
        assert tool.category == "browser"
        assert isinstance(tool.parameters, dict) and tool.parameters


@pytest.mark.skipif(not _PLAYWRIGHT_PRESENT, reason="playwright not installed")
def test_register_browser_tools_registers_all_six() -> None:
    registry = ToolRegistry()
    count = register_browser_tools(registry)
    assert count == 6
    assert set(registry._tools) >= _EXPECTED_BROWSER_TOOLS
    # Spec generation must work for the newly registered tools.
    specs = {s["function"]["name"] for s in registry.get_openai_specs()}
    assert specs >= _EXPECTED_BROWSER_TOOLS


def test_register_browser_tools_gated_on_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """When playwright is absent, no browser tools are registered (no call-time traps)."""

    def _no_playwright(name: str):  # noqa: ANN202
        if name == "playwright":
            return None
        return importlib.util.find_spec(name)

    monkeypatch.setattr("importlib.util.find_spec", _no_playwright)
    registry = ToolRegistry()
    assert register_browser_tools(registry) == 0
    assert len(registry) == 0


@pytest.mark.skipif(not _PLAYWRIGHT_PRESENT, reason="playwright not installed")
def test_a_server_has_the_browser_tools_through_its_row_and_a_bare_tool_set_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from tests import plugin_view_fixture as views
    from thomas.core.config import load_config
    from thomas.server import app_core
    from thomas.server.app_helpers import _build_tools
    from thomas.server.app_keys import APP_TOOLS
    from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    assert not set(_build_tools(load_config())._tools) & _EXPECTED_BROWSER_TOOLS

    async def on_a_server() -> set[str]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            return {tool.name for tool in app[APP_TOOLS].list_tools()}

    assert asyncio.run(on_a_server()) >= _EXPECTED_BROWSER_TOOLS
