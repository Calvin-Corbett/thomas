"""A headless or scheduled run has the browser tools the chat page has (2026-09-05).

A scheduled task asked to open a page tried the shell twice and fell back to
the web extractor: the CLI's tool registry never registered the browser
tools, so `thomas chat` and every scheduled task could not drive a browser.
"""

from __future__ import annotations

import importlib.util

import pytest

from thomas.cli._commands_base import _build_tools
from thomas.core.config import AppConfig, ModelConfig


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="playwright is not installed")
def test_the_cli_registry_offers_the_browser_tools_and_their_parity_layer(tmp_path) -> None:
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    config.tools.sandbox_root = str(tmp_path)
    registry = _build_tools(config)
    names = set(registry._tools)
    assert {"browser.open", "browser.click", "browser.type"} <= names
    # the sensitive-site pause and the console/network readers ride along, as on the server
    assert {"browser.console", "browser.network"} <= names
