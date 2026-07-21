"""Async ReAct agent loop with streaming, parallel tools, and context management.

The core execution engine for Thomas. Handles:
- Streaming LLM responses to the caller in real-time
- Parallel tool execution when tools are independent
- Context window tracking and overflow prevention via token counting
- Automatic conversation trimming when approaching context limits
- Configurable iteration limits with stop conditions
- Error recovery with retries and graceful degradation
- Memory context injection

This is a thin facade that delegates to specialized modules:
- loop_core: Message building, initialization, routing helpers
- loop_tools: Tool selection and execution
- loop_streaming: Memory, library, token management
- loop_planning: Response sanitization, nudging, and the main run() loop
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from thomas.agent.hook_events import HookEvent, emit_hook
from thomas.agent.loop_core import AgentLoop as _AgentLoopBase
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_execution import _agent_loop_run
from thomas.agent.loop_helpers import _coerce_async_iterator
from thomas.agent.loop_planning import (
    assume_and_proceed_nudge,
    full_auto_nudge,
    looks_like_clarifying_question,
    routing_input_text,
    sanitize_assistant_text,
)
from thomas.agent.loop_streaming import (
    apply_memory_policy,
    auto_capture_research,
    build_token_report,
    capture_profile_hints,
    input_continuity_hint,
    normalize_usage,
    record_event,
    retrieve_library,
    retrieve_memory,
    session_usage_snapshot,
    usage_delta,
    usage_from_event_payload,
)
from thomas.agent.loop_tools import execute_tools, parse_tool_args, select_tools
from thomas.core.events import AgentEvent

if TYPE_CHECKING:
    from thomas.agent.routing import RouteDecision

log = logging.getLogger(__name__)


class AgentLoop(_AgentLoopBase):
    """Extended agent loop with main execution."""

    def _select_tools(
        self,
        prompt: str,
        policy: str = "auto",
        route: RouteDecision | None = None,
    ) -> list[dict[str, Any]] | None:
        """Select tool exposure policy with Smart Lazy Loading."""
        return select_tools(self, prompt, policy=policy, route=route)

    def _parse_tool_args(self, raw_args: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Parse tool arguments with repair heuristics for weak model outputs."""
        return parse_tool_args(self, raw_args)

    async def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        iteration: int,
    ) -> AsyncIterator[AgentEvent]:
        """Execute tool calls, running independent calls in parallel."""
        try:
            tool_stream = await _coerce_async_iterator(
                execute_tools(self, tool_calls, iteration),
                source="execute_tools",
            )
        except TypeError as exc:
            raise TypeError(f"Tool stream is not async iterable: {exc}") from exc

        async for event in tool_stream:
            yield event

    def _retrieve_memory(
        self,
        prompt: str,
        mode: str = "auto",
        *,
        budget_override: int | None = None,
    ) -> str:
        """Retrieve memory context for the prompt."""
        return retrieve_memory(self, prompt, mode=mode, budget_override=budget_override)

    def _apply_memory_policy(self, route: RouteDecision) -> None:
        """Apply per-turn memory policy."""
        apply_memory_policy(self, route)

    def _retrieve_library(self, prompt: str, route: RouteDecision) -> str:
        """Retrieve context from research library."""
        return retrieve_library(self, prompt, route)

    def _auto_capture_research(
        self,
        *,
        route: RouteDecision,
        query: str,
        answer: str,
        job_type: str | None = None,
    ) -> None:
        """Persist research-heavy answers into the external library."""
        auto_capture_research(self, route=route, query=query, answer=answer, job_type=job_type)

    def _record_event(self, etype: str, text: str) -> None:
        """Record an event in memory."""
        record_event(self, etype, text)

    def _capture_profile_hints(self, text: str) -> None:
        """Promote stable user hints into global pins."""
        capture_profile_hints(self, text)

    def _build_token_report(
        self,
        *,
        prompt_text: str,
        usage_obj: dict[str, int],
        mode: str,
        iterations: int,
        peak_context_tokens: int,
        avg_context_tokens: int,
        memory_tokens: int,
        tool_chars_total: int,
        tool_chars_kept: int,
    ) -> dict[str, Any]:
        """Build a comprehensive token usage report."""
        return build_token_report(
            self,
            prompt_text=prompt_text,
            usage_obj=usage_obj,
            mode=mode,
            iterations=iterations,
            peak_context_tokens=peak_context_tokens,
            avg_context_tokens=avg_context_tokens,
            memory_tokens=memory_tokens,
            tool_chars_total=tool_chars_total,
            tool_chars_kept=tool_chars_kept,
        )

    @staticmethod
    def _normalize_usage(prompt_tokens: Any, completion_tokens: Any, total_tokens: Any) -> dict[str, int]:
        """Normalize and validate token counts."""
        return normalize_usage(prompt_tokens, completion_tokens, total_tokens)

    def _session_usage_snapshot(self) -> dict[str, int]:
        """Get current session usage from LLM client."""
        return session_usage_snapshot(self)

    def _usage_from_event_payload(self, payload: Any) -> dict[str, int]:
        """Extract usage from event payload."""
        return usage_from_event_payload(payload)

    def _usage_delta(self, before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        """Calculate the difference between two usage snapshots."""
        return usage_delta(before, after)

    def _routing_input_text(self, prompt_text: str) -> tuple[str, str]:
        """Optionally augment routing input with prior assistant context."""
        return routing_input_text(self, prompt_text)

    def _input_continuity_hint(self, prompt_text: str) -> str:
        """Infer whether the user just supplied data requested in the prior turn."""
        return input_continuity_hint(self, prompt_text)

    def _sanitize_assistant_text(
        self,
        text: str,
        *,
        prompt_text: str,
        route: RouteDecision,
        route_input_source: str,
        pending_tool_calls: int,
    ) -> tuple[str, bool]:
        """Apply response hygiene: remove thought leakage + premature follow-ups."""
        return sanitize_assistant_text(
            self,
            text,
            prompt_text=prompt_text,
            route=route,
            route_input_source=route_input_source,
            pending_tool_calls=pending_tool_calls,
        )

    @staticmethod
    def _looks_like_clarifying_question(text: str) -> bool:
        """Check if text looks like a clarifying question."""
        return looks_like_clarifying_question(text)

    @staticmethod
    def _claims_execution(text: str) -> bool:
        """Heuristic detector for fabricated execution claims in plain text."""
        low = str(text or "").strip().lower()
        if not low:
            return False
        if "?" in low:
            return False
        if re.search(
            r"\b(cannot|can't|unable|don't have access|do not have access|missing access|missing credentials)\b",
            low,
        ):
            return False

        patterns = (
            r"\bi(?:'ve| have)?\s+(created|written|saved|executed|ran|launched|completed|finished)\b",
            r"\bfile\s+(saved|written|created)\b",
            r"\breport\s+(saved|written|created)\b",
            r"\bhere(?:'s| is)\s+the\s+output\b",
            r"\b\d+\s+agents?\s+running\b",
            r"\bagents?\s+(running|launched|started)\b",
        )
        return any(re.search(pattern, low) for pattern in patterns)

    @staticmethod
    def _full_auto_nudge(prompt_text: str, retry_index: int) -> str:
        """Generate nudge for Autonomy level 4."""
        return full_auto_nudge(prompt_text, retry_index)

    @staticmethod
    def _assume_and_proceed_nudge(
        prompt_text: str,
        *,
        retry_index: int,
        question_cap: int,
        questions_seen: int,
        route_input_source: str,
    ) -> str:
        """Generate nudge to assume defaults and proceed."""
        return assume_and_proceed_nudge(
            prompt_text,
            retry_index=retry_index,
            question_cap=question_cap,
            questions_seen=questions_seen,
            route_input_source=route_input_source,
        )

    async def _audit_action(
        self,
        *,
        kind: str,
        tool_call_id: str = "",
        tool_name: str = "",
        decision: str = "",
        reason: str = "",
        payload: Any = None,
    ) -> None:
        """Best-effort action audit event for tool lifecycle tracing."""
        audit = self._action_audit
        if audit is None:
            return
        try:
            await audit.log_async(
                kind=kind,
                run_id=self._run_id,
                session_id=self._session_id,
                tool_call_id=str(tool_call_id or ""),
                tool_name=str(tool_name or ""),
                decision=str(decision or ""),
                reason=str(reason or ""),
                payload=payload if payload is not None else {},
            )
        except Exception as e:  # REVIEWED: log-and-continue — optional audit logging
            log.debug("action audit failed (%s/%s): %s", kind, tool_name, e)

    async def run(
        self,
        prompt: Any,
        *,
        intent_text: str | None = None,
        mode: str = "auto",
        tools_policy: str = "auto",
        token_economy: str = "optimal",
        max_iterations: int | None = None,
        job_type: str | None = None,
        _quality_retry_count: int = 0,
        _quality_carry_forward_events: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent loop, yielding events as they occur.

        See _agent_loop_run for full documentation.
        """
        # Hook surface (run category): run_start fires before the first event and
        # run_end fires exactly once when the run is exhausted or closed.
        await emit_hook(
            self,
            HookEvent.RUN_START,
            {
                "run_id": self._run_id,
                "session_id": self._session_id,
                "mode": mode,
                "tools_policy": tools_policy,
            },
        )
        try:
            async for event in _agent_loop_run(
                self,
                prompt,
                intent_text=intent_text,
                mode=mode,
                tools_policy=tools_policy,
                token_economy=token_economy,
                max_iterations=max_iterations,
                job_type=job_type,
                _quality_retry_count=_quality_retry_count,
                _quality_carry_forward_events=_quality_carry_forward_events,
            ):
                yield event
        finally:
            await emit_hook(
                self,
                HookEvent.RUN_END,
                {"run_id": self._run_id, "session_id": self._session_id},
            )


# Public exports for backward compatibility
__all__ = [
    "AgentLoop",
    "LoopState",
]
