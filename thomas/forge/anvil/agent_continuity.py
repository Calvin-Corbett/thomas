"""An unpicked conversation stays on the agent that ran it.

With no agent picked, Build resolves one from the registry, and Thomas's own loop
wins a Claude model as soon as an Anthropic key is present. The key alone used to
decide that, for every conversation: once ``ANTHROPIC_API_KEY`` was in the
server's environment, a conversation whose earlier turns ran on Claude Code
continued on Thomas's loop, billed to the key, and nothing said so.

So an existing conversation keeps the agent its last turn ran on, and the report
says why. A pick still wins, and a new conversation still gets the default.
The picker names either before you send: asked with the open conversation, its
route answers from :func:`kept_agent` too ("Default (Claude Code)"). A turn from before
the picker has no ``agent``; its ``claude:`` model prefix named Claude Code, the
only agent a Claude model then had.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from thomas.core.coding_agents import CodingAgentSpec, builtin_registry

from .forge_code_settings import ForgeCodeSettings


def agent_that_ran(conversation: dict[str, Any] | None) -> str:
    """The agent the conversation's latest agent turn ran on, or "" when none says."""
    for turn in reversed((conversation or {}).get("turns") or []):
        if not isinstance(turn, dict) or turn.get("role") != "agent":
            continue
        agent = str(turn.get("agent") or "").strip()
        if agent:
            return agent
        model = str(turn.get("model") or "").strip().lower()
        if model.startswith("claude:"):
            return "claude_code"
        return "thomas" if model else ""
    return ""


def kept_agent(conversation: dict[str, Any] | None, *, family: str, resolved: str) -> CodingAgentSpec | None:
    """The agent an unpicked turn of this conversation stays on instead of ``resolved``.

    None when the registry's answer stands: the conversation names no agent, it
    names ``resolved`` already, or its agent cannot run and reach ``family`` now.
    Build (:func:`keep_conversation_agent`) and the picker's route both ask this.
    """
    previous = agent_that_ran(conversation)
    spec = builtin_registry().get(previous) if previous else None
    if spec is None or spec.id == resolved or not spec.reaches_family(family):
        return None
    return spec


def kept_reason(spec: CodingAgentSpec) -> str:
    """The sentence the run report and the picker give for a kept agent."""
    return (
        f"No agent was picked, so this conversation stayed on {spec.label}, which ran its earlier turns. "
        "Pick an agent to change it."
    )


def keep_conversation_agent(settings: ForgeCodeSettings, conversation: dict[str, Any] | None) -> ForgeCodeSettings:
    """``settings`` on the agent this conversation already ran on, when nobody picked one.

    Only an agent that can still run and reach the model is kept; otherwise the
    registry's answer stands, as it did before.
    """
    if settings.agent_picked:
        return settings
    spec = kept_agent(conversation, family=settings.family, resolved=settings.agent)
    if spec is None:
        return settings
    plan = spec.plan(settings.dispatch_model)
    return replace(settings, agent=spec.id, agent_profile=plan.profile, agent_reason=kept_reason(spec))


__all__ = ["agent_that_ran", "keep_conversation_agent", "kept_agent", "kept_reason"]
