"""Tool selection, parsing, and execution for agent loop.

Provides:
- Smart tool selection with token budgeting
- Tool argument parsing with repair heuristics
- Tool execution delegation to loop_tool_exec
"""

from __future__ import annotations

import logging
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
from thomas.models.protocol import profile_prefers_always_tools

if TYPE_CHECKING:
    from thomas.agent.loop_core import AgentLoop

log = logging.getLogger(__name__)


def select_tools(
    agent: AgentLoop,
    prompt: str,
    policy: str = "auto",
    route: RouteDecision | None = None,
) -> list[dict[str, Any]] | None:
    """Select tools to expose with Smart Lazy Loading.

    To prevent token bloat (30k/turn), we only load:
    1. Core tools (always useful)
    2. Contextually relevant tools (via semantic search)

    Parameters:
        agent: The AgentLoop instance
        prompt: The user prompt
        policy: "never" (no tools), "auto" (heuristic), "always" (broad selection)
        route: The routing decision with contextual path info

    Returns:
        List of tool specs in OpenAI format, or None if no tools should be exposed
    """
    if len(agent.tools) == 0:
        return None

    if policy == "never":
        return None

    remote_profile = profile_prefers_always_tools(agent.llm.config)
    explicit_action = agent._has_explicit_action_intent(prompt)
    project_related = agent._is_project_related_prompt(prompt)
    if policy == "auto" and route is not None:
        low_intent_route = agent._is_low_intent_route(route.path)
        if low_intent_route and not explicit_action and not project_related and not remote_profile:
            # Keep casual/meta turns lightweight for LOCAL models only.
            # Remote/API models can handle tool definitions cheaply, and
            # suppressing tools when the user wants action is far worse than
            # the token cost of including them.
            return None

    # 1. Identify Core Tools (Always included in Auto/Always)
    # These are essential for basic agent function.
    core_patterns = {
        "fs.read",
        "fs.write",
        "fs.list",
        "fs.search",  # Filesystem
        "diff.",  # Diff/patch editing (preferred over fs.write for edits)
        "memory.",  # Memory
        "proc.run",  # Terminals
        "code.search",
        "code.view",  # Codebase
        "obs.screenshot",  # Vision (lightweight)
    }

    all_tools = agent.tools.list_tools()
    core_tools = []
    other_tools = []

    for t in all_tools:
        # Check if matching core pattern
        is_core = False
        t_name = t.name.lower()
        for p in core_patterns:
            if p in t_name:
                is_core = True
                break
        if is_core:
            core_tools.append(t)
        else:
            other_tools.append(t)

    # 2. Determine Budget for "Extra" Tools
    # REMOVED: fast-pass for < 40 tools. We now ALWAYS filter to be safe.
    # The user reported "tried using all tools again" which suggests 39 tools
    # might still be 15k tokens if they are large ones.

    # 3. Smart Selection (Semantic Search)
    # If we have too many tools, we MUST select relevant ones.

    # In 'Always' mode or specific routes, we are generous.
    # In 'Casual' or irrelevant prompts, we are strict.

    target_extra_count = 12
    if policy == "always":
        target_extra_count = 24
    elif route and route.path in ("coding_task", "debug_audit"):
        target_extra_count = 18

    # Search for relevance
    # Use a generous limit for search to get candidates
    relevant_candidates = agent.tools.search(prompt, limit=target_extra_count)

    # Combine Core + Relevant
    # Use a dictionary to dedup by name
    final_selection = {t.name: t for t in core_tools}
    for t in relevant_candidates:
        final_selection[t.name] = t

    # 4. Fallback for "Project Related" prompts
    # If the prompt mentions specific domains not caught by search, add them?
    # The search() method handles keyword overlap, so it should catch "browser" or "database".

    # 5. Guarded Mode (Autonomy 2) check
    # If in guarded mode and policy is auto, only return if explicit intent is impactful.
    # (Preserving original logic)
    if (
        not final_selection
        and route is not None
        and route.path in ("coding_task", "debug_audit", "planning", "research")
        and policy in ("auto", "always")
        and not (agent._is_low_intent_route(route.path) and not explicit_action)
    ):
        fallback_count = min(len(all_tools), max(1, target_extra_count))
        for t in all_tools[:fallback_count]:
            final_selection[t.name] = t

    if agent._autonomy_level == 2 and policy == "auto":
        if not explicit_action and not project_related:
            # In guarded mode, if no clear intent, hide tools (except maybe read-only?)
            # For now preserving strictness: return None
            return None

    if (
        not final_selection
        and remote_profile
        and policy in ("auto", "always")
        and (
            explicit_action
            or project_related
            or (route and route.path in ("coding_task", "debug_audit", "planning", "research"))
        )
        and not (route is not None and agent._is_low_intent_route(route.path) and not explicit_action)
    ):
        # Remote/API profiles should still have tool access when the task is action-oriented.
        fallback_count = min(len(all_tools), max(1, target_extra_count))
        for t in all_tools[:fallback_count]:
            final_selection[t.name] = t

    if not final_selection:
        return None

    # Convert to OpenAI specs
    return [t.get_spec().to_openai() for t in final_selection.values()]


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
