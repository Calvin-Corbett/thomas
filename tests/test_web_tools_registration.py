"""Regression coverage for live web-research tool registration."""

from __future__ import annotations

from thomas.core.config import load_config
from thomas.server.app_helpers import _build_tools

_EXPECTED_WEB_TOOLS = {"web.search", "web.fetch"}


def test_build_tools_includes_web_research_tools() -> None:
    registry = _build_tools(load_config())

    assert set(registry._tools) >= _EXPECTED_WEB_TOOLS
    assert {registry.get(name).category for name in _EXPECTED_WEB_TOOLS} == {"web"}

    specs = {spec["function"]["name"] for spec in registry.get_openai_specs()}
    assert specs >= _EXPECTED_WEB_TOOLS
