"""Response planning, sanitization, routing, and main execution loop.

Provides:
- Response sanitization and thought-leak removal
- Clarifying question detection and nudging
- Routing input analysis and continuity hints
- Main async run() loop for agent execution
- Action auditing
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from thomas.agent.response_tone import (
    apply_directness_constraints,
    apply_social_tone_adjustments,
    prompt_has_frustration_signal,
    strip_internal_reasoning_narration,
    strip_tool_call_artifacts,
    strip_unprompted_workspace_references,
)
from thomas.agent.routing import RouteDecision

if TYPE_CHECKING:
    from thomas.agent.loop_core import AgentLoop

log = logging.getLogger(__name__)


def strip_premature_followup(text: str) -> tuple[str, bool]:
    """Remove standalone follow-up lines that frequently derail in-progress tasks."""
    src = str(text or "")
    if not src.strip():
        return src, False

    # Remove standalone follow-up lines that frequently derail in-progress tasks.
    line_patterns = (
        r"^\s*anything else\??\s*$",
        r"^\s*what(?:'s| is)? next\??\s*$",
        r"^\s*what would you like (?:me )?to do next\??\s*$",
        r"^\s*what do you want(?: me)? to do next\??\s*$",
        r"^\s*how can i help(?: you)?(?: further)?\??\s*$",
        r"^\s*how can i assist(?: you)?(?: [a-z]+){0,4}\??\s*$",
        r"^\s*what can i help with\??\s*$",
    )
    removed = False
    lines: list[str] = []
    for line in src.splitlines():
        if any(re.search(p, line, re.I) for p in line_patterns):
            removed = True
            continue
        lines.append(line)
    out = "\n".join(lines)

    # Remove trailing generic follow-up question at end of a sentence.
    trailing = re.compile(
        r"(?:\s*(?:anything else\??|what(?:'s| is)? next\??|what would you like (?:me )?to do next\??|what do you want(?: me)? to do next\??|how can i help(?: you)?(?: further)?\??|how can i assist(?: you)?(?: [a-z]+){0,4}\??|what can i help with\??)\s*)+$",
        re.I,
    )
    new_out = trailing.sub("", out).rstrip()
    if new_out != out:
        removed = True
        out = new_out
    return (out if out.strip() else src), removed


def sanitize_assistant_text(
    agent: AgentLoop,
    text: str,
    *,
    prompt_text: str,
    route: RouteDecision,
    route_input_source: str,
    pending_tool_calls: int,
) -> tuple[str, bool]:
    """Apply response hygiene: remove thought leakage + premature follow-ups."""
    src = str(text or "")
    if not src.strip():
        return src, False
    agent._last_sanitize_flags = {}
    if pending_tool_calls > 0:
        return src, False
    blocked_response = agent._is_blocked_response(src)
    path = str(getattr(route, "path", "") or "")
    action_path = path in ("coding_task", "debug_audit", "planning", "research")
    continuation_turn = route_input_source == "history_augmented" or agent._is_ack_turn(prompt_text)
    frustrated_turn = prompt_has_frustration_signal(prompt_text)
    changed = False
    out = src
    flags = {
        "followup": False,
        "thought_leak": False,
        "tool_artifact": False,
        "directness": False,
        "social": False,
        "workspace": False,
    }

    if (action_path or continuation_turn or frustrated_turn) and not blocked_response:
        out, removed = strip_premature_followup(out)
        if removed:
            flags["followup"] = True
            changed = True

    out, thought_changed = strip_internal_reasoning_narration(out, prompt_text=prompt_text)
    if thought_changed:
        flags["thought_leak"] = True
        changed = True

    out, artifact_changed = strip_tool_call_artifacts(out, prompt_text=prompt_text)
    if artifact_changed:
        flags["tool_artifact"] = True
        changed = True

    if not blocked_response:
        out, directness_changed = apply_directness_constraints(out, prompt_text=prompt_text)
        if directness_changed:
            flags["directness"] = True
            changed = True

    out, social_changed = apply_social_tone_adjustments(out, prompt_text=prompt_text)
    if social_changed:
        flags["social"] = True
        changed = True
    if agent._is_low_intent_route(path):
        out, path_changed = strip_unprompted_workspace_references(out, prompt_text=prompt_text)
        if path_changed:
            flags["workspace"] = True
            changed = True
    agent._last_sanitize_flags = flags
    return out, changed


def looks_like_clarifying_question(text: str) -> bool:
    """Check if text looks like a clarifying question."""
    src = str(text or "").strip()
    if not src:
        return False
    low = src.lower()

    # Strong signals that the model is asking the user to clarify.
    has_question_shape = "?" in src or bool(
        re.search(
            r"\b(which|what|where|when|who|can you|could you|would you|do you want|should i|please provide)\b",
            low,
        )
    )
    if not has_question_shape:
        return False

    # If the model is explicitly blocked by credentials/permissions/secrets,
    # this can be a legitimate question and should not be force-suppressed.
    if re.search(
        r"\b(api key|token|password|credential|auth|permission|access|secret|login|otp|code)\b",
        low,
    ):
        return False
    if re.search(r"\b(cannot|can't|unable|impossible|missing|not available)\b", low):
        return False
    return True


def full_auto_nudge(prompt_text: str, retry_index: int) -> str:
    """Generate nudge for Autonomy level 4."""
    return (
        "Autonomy level 4 is enabled. Do not ask clarifying questions for this task unless "
        "it is genuinely impossible or unsafe. Inspect available context, choose sensible defaults, "
        "execute now, and report concrete actions taken. "
        f"(full_auto_retry={int(retry_index)}; original_request={prompt_text[:220]})"
    )


def assume_and_proceed_nudge(
    prompt_text: str,
    *,
    retry_index: int,
    question_cap: int,
    questions_seen: int,
    route_input_source: str,
) -> str:
    """Generate nudge to assume defaults and proceed."""
    return (
        "Continue execution now. Do not ask another clarifying question unless it is truly blocked by "
        "missing credentials, access, or unsafe constraints. Assume sensible defaults, state assumptions "
        "briefly, and proceed with concrete actions. "
        f"(clarification_retry={int(retry_index)}; clarification_cap={int(question_cap)}; "
        f"clarification_seen={int(questions_seen)}; route_input_source={str(route_input_source or 'prompt_only')}; "
        f"original_request={prompt_text[:220]})"
    )


def routing_input_text(agent: AgentLoop, prompt_text: str) -> tuple[str, str]:
    """Optionally augment routing input with prior assistant context on follow-ups."""
    src = str(prompt_text or "").strip()
    if not src:
        return src, "prompt_only"
    prev_assistant = agent._latest_assistant_message()
    if not prev_assistant:
        return src, "prompt_only"
    prev_l = prev_assistant.lower()
    is_follow_up = agent._is_ack_turn(src) or agent._looks_like_requested_input(src)
    if not is_follow_up:
        return src, "prompt_only"
    action_context = bool(
        re.search(
            r"\b(set ?up|setup|install|configure|connect|integrat|deploy|fix|implement|run|audit|test|refactor|token|chat id|user id|bot id)\b",
            prev_l,
        )
        or re.search(
            r"\b(please provide|send|share|which|what|where)\b",
            prev_l,
        )
    )
    if not action_context:
        return src, "prompt_only"
    routed = f"{prev_assistant}\nUser reply: {src}"
    return routed, "history_augmented"
