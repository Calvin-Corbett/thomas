"""A Chat turn's own deadline: the final, tool-restricted pass.

A Chat turn's whole budget used to be one specialist call bounded by
``tool_timeout_s`` -- described everywhere as a *per-tool* timeout, but
enforced (``specialists/base.py``) around the whole reasoning-specialist
call: every model pass plus every tool call. When it fired, the turn ended
in "The selected model timed out before it could finish. Please try
again.", which blames the model (it never actually failed) and hands the
next step to the user, even on Autopilot.

Round 1 tried to stop this by restricting the retry *token*, but
``ReasoningSpecialist`` never consulted the token when deciding which tools
to *offer* the model (only when actually executing one) -- so the retry
still offered every read tool, the model still tried them, and each got a
confusing "you have read-only access" denial with nothing to summarise.
This module fixes that at the source: the final pass's
:class:`~thomas.marketplace.orchestrator.protocol.DelegationContract` carries
``input_context["final_pass"] = True`` and a compacted digest of the first
pass's findings, which ``ReasoningSpecialist`` reads to build NO read tools
at all -- only ``send_task`` (level 3+, and only if the first pass has not
already started something effectful) or nothing. See
.superpowers/sdd/2026-09-23-thomas-works-on-himself/task-2b-fix-round-2.md.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from thomas.core.sandbox_links import strip_sandbox_links
from thomas.marketplace.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    DelegationResult,
    SpecialistStatus,
)

# The whole turn's own deadline, read from runtime settings (``tool_timeout_s``
# is a different knob -- see task-2b-fix-round-2.md, I2). No live setting
# provides this yet, so callers pass whatever ``getattr(..., "turn_deadline_s",
# DEFAULT_TURN_DEADLINE_S)`` finds; this constant is the honest fallback.
DEFAULT_TURN_DEADLINE_S = 150.0

# Minimum -- and, by construction, exact -- time reserved for the final pass:
# the primary pass is bounded by ``turn_deadline_s - FINAL_PASS_RESERVE_S``,
# so the final pass always starts with at least this much left.
FINAL_PASS_RESERVE_S = 20.0

# Tools/actions a first pass may already have taken that a final pass must
# never repeat (I4): a second send_task/update_task/operate call from a
# retried pass would create or touch real work twice.
_EFFECTFUL_TOOL_NAMES = {"send_task", "update_task", "operate"}

# The real ReasoningSpecialist reports a successful send_task/update_task as
# task_request/task_update, never as a tool_result (its own hand-off
# branches, reasoning.py) -- confirmed live: probe_i4_send_task_event_shape.py
# showed the event sequence ['thinking', 'task_request', 'text', 'done'] and
# no tool_result at all. already_acted()/send_task_allowed() key off "name",
# so a caller records one of these via record_action_event() first.
_TASK_EVENT_TOOL_NAMES = {"task_request": "send_task", "task_update": "update_task"}

# Contract input_context keys the final pass never carries forward: every
# capability except send_task (offered only when nothing effectful ran yet
# and the level allows it -- decided by the caller via ``send_task_allowed``).
_STRIPPED_CONTEXT_KEYS = ("update_task", "operate", "remember", "recall", "work_onboarding_update")

FINAL_PASS_INSTRUCTION = (
    "You are out of time for this turn. Hand this off as a background task if you can "
    "(send_task), or answer now with what you found so far and what you would do next. "
    "No files can be read this pass."
)

ALREADY_ACTED_INSTRUCTION = (
    "You already started a task or action this turn. Do not start another one -- summarise "
    "what you started and what happens next."
)


def resolve_turn_deadline_s(runtime_tools: Any) -> float:
    """The turn's own deadline in seconds, separate from ``tool_timeout_s``."""
    return float(getattr(runtime_tools, "turn_deadline_s", None) or DEFAULT_TURN_DEADLINE_S)


def primary_pass_timeout_s(turn_deadline_s: float) -> float:
    """The first pass's own budget: the turn deadline minus the final pass's reserve."""
    return max(1.0, float(turn_deadline_s) - FINAL_PASS_RESERVE_S)


def final_pass_budget(start: float, turn_deadline_s: float) -> float:
    """Seconds left for the final pass: at least ``FINAL_PASS_RESERVE_S``."""
    return max(FINAL_PASS_RESERVE_S, start + float(turn_deadline_s) - time.monotonic())


def record_action_event(tool_calls: list[dict[str, Any]], event: dict[str, Any]) -> None:
    """Append a task_request/task_update event to ``tool_calls`` with the
    synthetic "name" already_acted()/send_task_allowed() look for.
    """
    tool_calls.append({**event, "name": _TASK_EVENT_TOOL_NAMES[event.get("type")]})


def already_acted(tool_calls: list[dict[str, Any]]) -> bool:
    """True if the first pass already called an effectful tool (send_task/update_task/operate)."""
    return any(str(call.get("name") or "") in _EFFECTFUL_TOOL_NAMES for call in tool_calls)


def send_task_allowed(*, has_send_task: bool, autonomy_level: int, tool_calls: list[dict[str, Any]]) -> bool:
    """Whether the final pass may offer ``send_task``: level 3+, a callback was
    granted this turn, and the first pass has not already acted (I4).
    """
    return bool(has_send_task) and int(autonomy_level) >= 3 and not already_acted(tool_calls)


def compact_findings(tool_calls: list[dict[str, Any]], *, max_chars: int = 2_000) -> str:
    """A short, model-readable digest of the first pass's own read results.

    Skips action entries (send_task/update_task's task_request/task_update,
    recorded via ``record_action_event`` so already_acted() can see them --
    they carry no "result" and are not findings to summarise).
    """
    findings = [call for call in tool_calls if "result" in call]
    if not findings:
        return ""
    lines = [f"- {call.get('name') or 'tool'}: {str(call.get('result'))[:300]}" for call in findings]
    return "\n".join(lines)[:max_chars]


def build_final_pass_context(tool_calls: list[dict[str, Any]], *, acted: bool) -> str:
    """The text injected into the final pass's system prompt: findings + instruction."""
    findings = compact_findings(tool_calls)
    parts = [f"What the first pass already found:\n{findings}"] if findings else []
    parts.append(ALREADY_ACTED_INSTRUCTION if acted else FINAL_PASS_INSTRUCTION)
    return "\n\n".join(parts)


def final_pass_token(token: CapabilityToken, *, send_task_allowed: bool) -> CapabilityToken:
    """A token that permits at most ``send_task`` -- never a read/explore tool.

    ``CapabilityToken.permits_tool`` treats an EMPTY ``allowed_tools`` as
    unrestricted, so "nothing allowed" has to be a non-empty set no real tool
    name will ever match, never ``set()``.
    """
    allowed = {"send_task"} if send_task_allowed else {"__final_pass_no_tools__"}
    return dataclasses.replace(token, allowed_tools=allowed)


def final_pass_contract(
    contract: DelegationContract,
    *,
    timeout_seconds: float,
    tool_calls: list[dict[str, Any]],
    send_task_allowed: bool,
) -> DelegationContract:
    """A contract for the final pass: no read tools, the first pass's findings
    threaded in, and every effectful callback but ``send_task`` stripped.
    """
    acted = already_acted(tool_calls)
    ctx = dict(contract.input_context or {})
    ctx["final_pass"] = True
    ctx["final_pass_context"] = build_final_pass_context(tool_calls, acted=acted)
    if not send_task_allowed:
        ctx["send_task"] = None
    for key in _STRIPPED_CONTEXT_KEYS:
        ctx[key] = None
    return dataclasses.replace(contract, timeout_seconds=timeout_seconds, input_context=ctx)


def final_pass_status(error: str | None) -> SpecialistStatus:
    """The status a final pass's own error (if any) maps to."""
    if error is None:
        return SpecialistStatus.COMPLETED
    if any(token in error.lower() for token in ("timed out", "timeout")):
        return SpecialistStatus.TIMEOUT
    return SpecialistStatus.FAILED


def join_pass_texts(primary: str, final: str) -> str:
    """Join the two passes' visible text with a separator, matching what streams live."""
    return primary + ("\n\n" if primary else "") + final


async def consume_specialist_stream(
    specialist: Any,
    *,
    contract: DelegationContract,
    token: CapabilityToken,
    prompt: str,
    conversation: Any,
    memory_ctx: Any,
    dispatcher: Any,
    stream_text_events: bool,
) -> tuple[list[str], list[dict[str, Any]], list[str], int, str | None]:
    """Consume one ``specialist.execute()`` stream to completion.

    Returns ``(content_parts, tool_calls, thinking_parts, iterations, error)`` --
    the same shape ``brain.py``'s own primary-pass loop tracks, so both the
    primary and final pass can be folded into one ``DelegationResult``.
    """
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    thinking_parts: list[str] = []
    iterations = 0
    error: str | None = None
    async for event in specialist.execute(
        contract=contract,
        token=token,
        prompt=prompt,
        conversation_context=conversation.get_context_window(max_tokens=8_000),
        memory_context=memory_ctx.to_system_injection(),
    ):
        event_type = event.get("type", "")
        if event_type == "text":
            chunk = str(event.get("text", "") or "")
            content_parts.append(chunk)
            if stream_text_events and chunk:
                await dispatcher.emit_text(chunk)
        elif event_type == "thinking":
            thinking_parts.append(event.get("text", ""))
        elif event_type in ("tool_start", "tool_result", "tool_args"):
            await dispatcher.emit(event)
            if event_type == "tool_result":
                tool_calls.append(event)
        elif event_type in ("task_request", "task_update"):
            record_action_event(tool_calls, event)
        elif event_type == "done":
            iterations = event.get("iterations", 0)
        elif event_type == "error":
            error = event.get("error", "Unknown specialist error")
    return content_parts, tool_calls, thinking_parts, iterations, error


async def run_final_pass(
    result: DelegationResult,
    *,
    specialist: Any,
    contract: DelegationContract,
    token: CapabilityToken,
    prompt: str,
    conversation: Any,
    memory_ctx: Any,
    dispatcher: Any,
    stream_text_events: bool,
    autonomy_level: int,
    start: float,
    turn_deadline_s: float,
) -> None:
    """Run the final, restricted pass and fold it onto ``result`` in place.

    ``result`` already carries the primary pass's own content/tool_calls/
    thinking when this is called (brain.py sets those first); this appends
    the final pass's own and overwrites status/error/attempts/elapsed_ms.
    """
    allowed = send_task_allowed(
        has_send_task=bool(contract.input_context.get("send_task")),
        autonomy_level=autonomy_level,
        tool_calls=result.tool_calls,
    )
    budget = final_pass_budget(start, turn_deadline_s)
    primary_text = result.content
    if primary_text:
        await dispatcher.emit_text("\n\n")
    final_content, final_tools_used, final_thinking, iterations, error = await consume_specialist_stream(
        specialist,
        contract=final_pass_contract(
            contract, timeout_seconds=budget, tool_calls=result.tool_calls, send_task_allowed=allowed
        ),
        token=final_pass_token(token, send_task_allowed=allowed),
        prompt=prompt,
        conversation=conversation,
        memory_ctx=memory_ctx,
        dispatcher=dispatcher,
        stream_text_events=stream_text_events,
    )
    result.tool_calls = [*result.tool_calls, *final_tools_used]
    result.thinking = "\n".join(t for t in (result.thinking, *final_thinking) if t)
    result.iterations = iterations or result.iterations
    result.error = error
    result.status = final_pass_status(error)
    result.attempts = 2  # two passes ran, whatever the first pass's own retry count was
    combined = join_pass_texts(primary_text, "".join(final_content))
    result.content = strip_sandbox_links(combined) if error is None else combined
    result.elapsed_ms = int((time.monotonic() - start) * 1000)


__all__ = [
    "DEFAULT_TURN_DEADLINE_S",
    "FINAL_PASS_RESERVE_S",
    "already_acted",
    "build_final_pass_context",
    "compact_findings",
    "consume_specialist_stream",
    "final_pass_budget",
    "final_pass_contract",
    "final_pass_status",
    "final_pass_token",
    "join_pass_texts",
    "primary_pass_timeout_s",
    "record_action_event",
    "resolve_turn_deadline_s",
    "run_final_pass",
    "send_task_allowed",
]
