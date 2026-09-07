"""The browser tools for `thomas chat`, the REPL and every scheduled task.

The chat page's registry had them (thomas/server/app_helpers.py); the CLI's
never did, so a scheduled task asked to open a page tried the shell twice
and fell back to the web extractor (2026-09-05). Same gate as the server:
nothing registers unless Playwright is installed. The parity layer adds the
sensitive-site pause and the console and network readers.
"""

from __future__ import annotations

from typing import Any


def register_cli_browser_tools(registry: Any) -> int:
    """Register the browser tools and their parity layer; 0 when Playwright is absent."""
    try:
        from thomas.tools.browser import register_browser_tools
        from thomas.tools.browser_parity import install_browser_parity
    except (ImportError, ModuleNotFoundError):
        return 0
    count = int(register_browser_tools(registry) or 0)
    if count:
        install_browser_parity(registry)
    return count


__all__ = ["register_cli_browser_tools"]
