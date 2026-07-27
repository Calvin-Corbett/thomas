"""Protocol-safe assistant-response cleanup.

The frontier model owns prose, tone, structure, and whether to ask a question.
This module only removes local link targets that the browser cannot open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from thomas.agent.response_tone import strip_sandbox_links
from thomas.agent.routing import RouteDecision

if TYPE_CHECKING:
    from thomas.agent.loop_core import AgentLoop


def sanitize_assistant_text(
    agent: AgentLoop,
    text: str,
    *,
    prompt_text: str,
    route: RouteDecision,
    route_input_source: str,
    pending_tool_calls: int,
) -> tuple[str, bool]:
    """Remove unusable local link targets without rewriting model prose."""
    src = str(text or "")
    if not src.strip():
        return src, False
    agent._last_sanitize_flags = {}
    if pending_tool_calls > 0:
        return src, False
    del prompt_text, route, route_input_source
    out = strip_sandbox_links(src)
    changed = out != src
    agent._last_sanitize_flags = {"sandbox": changed}
    return out, changed
