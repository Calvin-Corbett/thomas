"""Tool exposure, parsing, and execution for agent loop.

Provides:
- Model-owned capability exposure
- Tool argument parsing with repair heuristics
- Tool execution delegation to loop_tool_exec
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from thomas.agent.loop_tool_exec import (
    execute_tools as _execute_tools_impl,
)
from thomas.agent.loop_tool_exec import (
    parse_tool_args as _parse_tool_args_impl,
)
from thomas.agent.routing import RouteDecision
from thomas.core.events import AgentEvent
from thomas.marketplace.observability import file_audit as _file_audit

if TYPE_CHECKING:
    from thomas.agent.loop_core import AgentLoop


def select_tools(
    agent: AgentLoop,
    prompt: str,
    policy: str = "auto",
    route: RouteDecision | None = None,
) -> list[dict[str, Any]] | None:
    """Expose registered capabilities without classifying the prompt.

    Parameters:
        agent: The AgentLoop instance
        prompt: Accepted for compatibility; never inspected here
        policy: Explicit capability control (``never``, ``auto``, ``always``)
        route: Accepted for compatibility; never used to hide capabilities

    Returns:
        Every registered tool spec, or ``None`` when tools are explicitly off
    """
    del prompt, route
    if len(agent.tools) == 0:
        return None

    if policy == "never":
        return None

    all_tools = agent.tools.list_tools()
    if not all_tools:
        return None

    return [tool.get_spec().to_openai() for tool in all_tools]


def parse_tool_args(
    agent: AgentLoop,
    raw_args: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse tool arguments with repair heuristics for weak model outputs."""
    return _parse_tool_args_impl(raw_args)


async def execute_tools(
    agent: AgentLoop,
    tool_calls: list[dict[str, Any]],
    iteration: int,
) -> AsyncIterator[AgentEvent]:
    """Execute tool calls, running independent calls in parallel."""
    async for event in _execute_tools_impl(
        agent,
        tool_calls,
        iteration,
        file_audit_module=_file_audit,
    ):
        yield event
