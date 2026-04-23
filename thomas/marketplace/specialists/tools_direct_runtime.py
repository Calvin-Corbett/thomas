"""Direct fast-path dispatcher for the tools specialist."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken
from thomas.marketplace.specialists.tools_direct_runtime_browser import handle_direct_runtime_browser
from thomas.marketplace.specialists.tools_direct_runtime_files import handle_direct_runtime_files
from thomas.marketplace.specialists.tools_direct_runtime_local import handle_direct_runtime_local


async def run_direct_fast_path(prompt: str, token: CapabilityToken) -> AsyncIterator[dict[str, Any]]:
    for handler in (
        handle_direct_runtime_files,
        handle_direct_runtime_local,
        handle_direct_runtime_browser,
    ):
        handled = False
        async for event in handler(prompt, token):
            handled = True
            yield event
        if handled:
            return
