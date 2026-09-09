"""Deterministic hook event surface for the Thomas agent loop.

This module is the single source of truth for the *plugin hook event surface* —
the named lifecycle events a plugin may observe during an agent run. It does not
introduce a second dispatch mechanism: events are delivered through the existing
``AgentLoop._run_plugin_hook`` invoker (see ``thomas.agent.loop_core``) which is
already wired to ``thomas.plugins.p108_plugin_hook_runner_core.run_hook`` at the
server boundary.

Six event *categories* make up the full surface, matching the agent run
lifecycle:

- ``run``        -> ``run_start`` / ``run_end``
- ``model``      -> ``model_call``
- ``tool``       -> ``tool_pre`` / ``tool_post``
- ``approval``   -> ``approval_requested``
- ``completion`` -> ``completion``
- ``failure``    -> ``failure``

Every canonical event maps to exactly one category (see ``_EVENT_CATEGORY``).
For backward compatibility with hooks already shipped, a handful of canonical
events also fire a legacy alias name (see ``_LEGACY_ALIASES``); the alias is an
*additional* dispatch, never a replacement, so existing ``before_model`` /
``before_tool`` / ``after_tool`` / ``after_response`` subscribers keep working.

Payload shapes are documented per-event in ``EVENT_PAYLOAD_KEYS`` so producers
(the agent loop call sites) and consumers (plugins, tests) agree on the contract.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class HookEventCategory(str, Enum):
    """The six lifecycle categories the hook surface must cover."""

    RUN = "run"
    MODEL = "model"
    TOOL = "tool"
    APPROVAL = "approval"
    COMPLETION = "completion"
    FAILURE = "failure"


class HookEvent(str, Enum):
    """Canonical, deterministic event names emitted by the agent loop."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    MODEL_CALL = "model_call"
    TOOL_PRE = "tool_pre"
    TOOL_POST = "tool_post"
    APPROVAL_REQUESTED = "approval_requested"
    COMPLETION = "completion"
    FAILURE = "failure"


# Each canonical event belongs to exactly one category. This mapping IS the
# coverage registry the acceptance surface is measured against.
_EVENT_CATEGORY: dict[HookEvent, HookEventCategory] = {
    HookEvent.RUN_START: HookEventCategory.RUN,
    HookEvent.RUN_END: HookEventCategory.RUN,
    HookEvent.MODEL_CALL: HookEventCategory.MODEL,
    HookEvent.TOOL_PRE: HookEventCategory.TOOL,
    HookEvent.TOOL_POST: HookEventCategory.TOOL,
    HookEvent.APPROVAL_REQUESTED: HookEventCategory.APPROVAL,
    HookEvent.COMPLETION: HookEventCategory.COMPLETION,
    HookEvent.FAILURE: HookEventCategory.FAILURE,
}

# Canonical event -> extra legacy names to fire for backward compatibility.
# These were the ad-hoc hook names emitted before the surface was unified; they
# remain wired so pre-existing plugins/tests do not regress.
_LEGACY_ALIASES: dict[HookEvent, tuple[str, ...]] = {
    HookEvent.MODEL_CALL: ("before_model",),
    HookEvent.TOOL_PRE: ("before_tool",),
    HookEvent.TOOL_POST: ("after_tool",),
    HookEvent.COMPLETION: ("after_response",),
}

# Documented required payload keys per canonical event. Producers must supply at
# least these keys; consumers may rely on them being present.
EVENT_PAYLOAD_KEYS: dict[HookEvent, tuple[str, ...]] = {
    HookEvent.RUN_START: ("run_id", "session_id", "mode", "tools_policy"),
    HookEvent.RUN_END: ("run_id", "session_id"),
    HookEvent.MODEL_CALL: ("messages", "model"),
    HookEvent.TOOL_PRE: ("name", "args"),
    HookEvent.TOOL_POST: ("name", "args", "ok", "result_text"),
    HookEvent.APPROVAL_REQUESTED: ("tool_name", "tool_call_id", "run_id", "reason"),
    HookEvent.COMPLETION: ("text",),
    HookEvent.FAILURE: ("error", "run_id"),
}


def category_of(event: HookEvent) -> HookEventCategory:
    """Return the lifecycle category for a canonical event."""

    return _EVENT_CATEGORY[event]


def event_names_for(event: HookEvent) -> tuple[str, ...]:
    """Return the wire names to dispatch for an event (canonical + legacy aliases)."""

    return (event.value, *_LEGACY_ALIASES.get(event, ()))


def covered_categories() -> frozenset[HookEventCategory]:
    """Return the set of categories the registry currently enumerates."""

    return frozenset(_EVENT_CATEGORY.values())


def event_surface() -> dict[HookEventCategory, tuple[str, ...]]:
    """Return the documented surface: canonical event names grouped by category."""

    grouped: dict[HookEventCategory, list[str]] = {c: [] for c in HookEventCategory}
    for event, category in _EVENT_CATEGORY.items():
        grouped[category].append(event.value)
    return {category: tuple(sorted(names)) for category, names in grouped.items()}


def category_for_name(name: str) -> HookEventCategory | None:
    """Reverse-lookup: map a dispatched wire name (canonical or legacy) to a category."""

    for event, category in _EVENT_CATEGORY.items():
        if name == event.value or name in _LEGACY_ALIASES.get(event, ()):
            return category
    return None


async def emit_hook(loop: Any, event: HookEvent, payload: dict[str, Any]) -> None:
    """Dispatch a hook-surface event via the loop's plugin-hook invoker.

    Resolves ``loop._run_plugin_hook`` defensively so any loop-like object works;
    a loop without an invoker is a no-op. The invoker itself
    (``AgentLoop._run_plugin_hook``) already isolates plugin failures, so a
    misbehaving plugin can never break the turn. Fires the canonical name first,
    then any legacy alias, so both new and pre-existing subscribers observe the
    event.
    """

    invoker = getattr(loop, "_run_plugin_hook", None)
    if invoker is None:
        return
    for name in event_names_for(event):
        await invoker(name, payload)


async def bridge_guardrails_event(loop: Any, evt_type: str, payload: dict[str, Any]) -> None:
    """Bridge a guardrails event-stream type onto the plugin hook surface.

    The approval request originates deep in the guardrails runner as a
    ``TOOL_APPROVAL_REQUIRED`` guardrails event. This maps it to the
    ``approval_requested`` hook so the approval category is covered by the same
    hook surface, without introducing a second dispatch path. Unrelated
    guardrails events are ignored.
    """

    if evt_type != "TOOL_APPROVAL_REQUIRED":
        return
    await emit_hook(
        loop,
        HookEvent.APPROVAL_REQUESTED,
        {
            "tool_name": payload.get("tool_name"),
            "tool_call_id": payload.get("tool_call_id"),
            "run_id": payload.get("run_id"),
            "reason": payload.get("reason"),
        },
    )


__all__ = [
    "HookEvent",
    "HookEventCategory",
    "EVENT_PAYLOAD_KEYS",
    "category_of",
    "category_for_name",
    "covered_categories",
    "event_names_for",
    "event_surface",
    "emit_hook",
    "bridge_guardrails_event",
]
