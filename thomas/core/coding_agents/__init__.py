"""Which coding agent runs a Build — a choice, not a consequence of the model.

Build has driven an outside coding agent since it learned to launch Claude Code
headless with a tool policy, an MCP bridge back to the Praxis run channel, and a
stream-json reader feeding Thomas's own events. What it could not do was let
anybody *choose*: the model's family decided the agent, so picking a Claude model
picked Claude Code and picking a GPT model picked Thomas's own loop.

This package is the agent side of that pair: the built-in agents and the registry
Build resolves a pick against. Thomas's own loop is the default and reaches Claude
through an Anthropic API key, so the product never *depends* on driving Claude
Code with somebody's personal subscription.

    from thomas.core.coding_agents import builtin_registry, resolve

    selection = resolve(builtin_registry(), model_id="claude-opus-5", requested="claude_code")
    selection.spec.dispatch   # 'thomas.forge.anvil.agent_passes:run_claude_code_pass'
"""

from __future__ import annotations

from thomas.core.coding_agents.builtins import (
    ANTHROPIC_API_ROOT,
    ANTHROPIC_KEY_ENV,
    ANTHROPIC_KEY_MISSING_MSG,
    BUILTIN_AGENT_IDS,
    BUILTIN_AGENTS,
    CLAUDE_CODE_AGENT,
    THOMAS_AGENT,
    THOMAS_FORGE_PROFILE,
    THOMAS_GPT_PROFILE,
    anthropic_api_key,
    anthropic_api_root,
    read_stored_anthropic_key_with,
    stored_anthropic_key,
)
from thomas.core.coding_agents.families import (
    FAMILIES,
    UNKNOWN_FAMILY,
    is_claude_model,
    is_gpt_model,
    model_family,
    strip_wire_prefix,
)
from thomas.core.coding_agents.registry import (
    DEFAULT_AGENT_ID,
    AgentCannotRunModel,
    AgentSelection,
    CodingAgentRegistry,
    UnknownAgent,
    resolve,
)
from thomas.core.coding_agents.spec import (
    AgentAvailability,
    AgentLaunchPlan,
    AgentRunRequest,
    CodingAgentSpec,
)

__all__ = [
    "ANTHROPIC_API_ROOT",
    "ANTHROPIC_KEY_ENV",
    "ANTHROPIC_KEY_MISSING_MSG",
    "BUILTIN_AGENTS",
    "BUILTIN_AGENT_IDS",
    "CLAUDE_CODE_AGENT",
    "DEFAULT_AGENT_ID",
    "FAMILIES",
    "THOMAS_AGENT",
    "THOMAS_FORGE_PROFILE",
    "THOMAS_GPT_PROFILE",
    "UNKNOWN_FAMILY",
    "AgentAvailability",
    "AgentCannotRunModel",
    "AgentLaunchPlan",
    "AgentRunRequest",
    "AgentSelection",
    "CodingAgentRegistry",
    "CodingAgentSpec",
    "UnknownAgent",
    "anthropic_api_key",
    "anthropic_api_root",
    "builtin_registry",
    "is_claude_model",
    "is_gpt_model",
    "model_family",
    "read_stored_anthropic_key_with",
    "resolve",
    "stored_anthropic_key",
    "strip_wire_prefix",
]


def builtin_registry() -> CodingAgentRegistry:
    """The built-in agents in a registry: what the picker offers and Build resolves against."""
    store = CodingAgentRegistry()
    for spec in BUILTIN_AGENTS:
        store.register(spec)
    return store
