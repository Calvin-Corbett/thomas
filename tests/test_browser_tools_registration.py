"""Regression tests for browser-tool wiring into the live tool registry.

The 6 Playwright ``Tool`` subclasses in ``thomas/tools/browser.py`` were
defined but never registered into the agent/server ``ToolRegistry``
(wiring-audit finding browser-02 / tools-01). These tests lock in that they
are reachable through both the dedicated ``register_browser_tools`` helper and
the server's ``_build_tools`` hub when Playwright is installed.
"""

from __future__ import annotations

import importlib.util

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
def test_build_tools_includes_browser_tools() -> None:
    from thomas.core.config import load_config
    from thomas.server.app_helpers import _build_tools

    registry = _build_tools(load_config())
    assert set(registry._tools) >= _EXPECTED_BROWSER_TOOLS
