"""OrchestratorBrain — Thomas's core delegation engine.

Thomas is a BRAIN.  He never executes tools or writes code himself.
He classifies intent, creates delegation contracts, dispatches to
specialist sub-agents, validates their output, and synthesises the
final response.

Architecture synthesised from:
    - OpenAI Agents SDK: explicit handoffs with schema validation
    - Google DeepMind: contract-first delegation, 4.4x error reduction
    - Microsoft Agent Framework: graph-based execution state
    - Anthropic Claude SDK: brain + specialist model
    - CrewAI: controlled hierarchies with allowed_agents
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from thomas.agent.dispatch import DispatchDecision, should_dispatch
from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.chat.thinking import ThinkingTracker
from thomas.marketplace.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    DelegationPhase,
    DelegationResult,
    RouteDecision,
    SpecialistStatus,
)
from thomas.marketplace.orchestrator.registry import SpecialistRegistry

log = logging.getLogger(__name__)

_STATUS_FOLLOWUP_RE = (
    r"\b(?:status|progress|update|done yet|finished|still running|"
    r"what'?s happening|where are we|how(?:'s| is) (?:that|it|this|the task|the project|the background work) going)\b"
)
_BACKGROUND_REFERENCE_RE = r"\b(?:background|worker|delegat|parallel)\b"
_TOOLS_ROUTE_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    r"\b(?:file|files|tool|tools)\b.*\b(?:repo|repository|workspace|folder|directory|path)\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\b(?:shell|command|directory listing|list files)\b)",
    re.I,
)


def _wants_background_status(prompt: str) -> bool:
    import re

    return bool(re.search(_STATUS_FOLLOWUP_RE, str(prompt or ""), re.I))


def _should_answer_background_status_directly(prompt: str, active_tasks: list[dict[str, Any]] | None) -> bool:
    import re

    text = str(prompt or "").strip().lower()
    if not _wants_background_status(text):
        return False
    if active_tasks:
        return True
    return bool(re.search(_BACKGROUND_REFERENCE_RE, text, re.I))


def _summarize_background_status(active_tasks: list[dict[str, Any]] | None) -> str:
    rows = [dict(row or {}) for row in list(active_tasks or []) if isinstance(row, dict)]
    if not rows:
        return "No background work is running in this thread."

    active_rows: list[dict[str, Any]] = []
    completed_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("state") or "").strip().lower()
        if state in {"queued", "requested", "classified", "claimed", "executing", "running", "in_progress"}:
            active_rows.append(row)
        elif state == "completed":
            completed_rows.append(row)
        elif state in {"failed", "abandoned", "cancelled"}:
            failed_rows.append(row)
        else:
            other_rows.append(row)

    def _detail(row: dict[str, Any]) -> str:
        summary = str(row.get("summary") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        state = str(row.get("state") or "unknown").replace("_", " ").strip()
        if summary and progress and progress != summary:
            return f"{summary} ({state}: {progress})"
        if summary:
            return f"{summary} ({state})"
        if progress:
            return f"{progress} ({state})"
        return state

    if active_rows:
        lead = "Background work is still running in this thread."
        lines = [lead]
        for row in active_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    if completed_rows and not failed_rows:
        lead = "Background work has completed in this thread."
        lines = [lead]
        for row in completed_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    if failed_rows and not completed_rows:
        lead = "Background work finished with issues in this thread."
        lines = [lead]
        for row in failed_rows[:2]:
            lines.append(f"- {_detail(row)}")
        return "\n".join(lines)

    lines = ["Background work in this thread has mixed outcomes."]
    for row in (active_rows + completed_rows + failed_rows + other_rows)[:3]:
        lines.append(f"- {_detail(row)}")
    return "\n".join(lines)


# Default token budgets by mode
_MODE_BUDGETS = {
    "fast": 1_500,
    "auto": 4_000,
    "thinking": 8_000,
    "max": 16_000,
}


class OrchestratorBrain:
    """Pure orchestrator that delegates all work to specialists.

    Parameters
    ----------
    config:
        Thomas AppConfig.
    llm:
        LLM client for the brain's own reasoning (routing, synthesis).
    memory_engine:
        Thomas's MemoryEngine instance.
    registry:
        SpecialistRegistry with all available specialists.
    """

    def __init__(
        self,
        config: Any,
        llm: Any,
        memory_engine: Any,
        registry: SpecialistRegistry,
    ) -> None:
        self.config = config
        self.llm = llm
        self.memory_engine = memory_engine
        self.registry = registry

    async def process_message(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        *,
        mode: str = "auto",
        autonomy_level: int = 3,
        token_economy: str = "optimal",
        images: list[dict[str, Any]] | None = None,
        is_first_message: bool = False,
        active_task_digest: str = "",
        active_tasks: list[dict[str, Any]] | None = None,
        dispatch_actionable: bool = True,
        background_ack_only: bool = False,
    ) -> ConversationManager:
        """Process a user message.

        In V2 chat Thomas should remain the only visible speaker. The route can
        still start background work in parallel, but the user-facing reply stays
        conversational here.
        """
        _ = images
        _ = is_first_message
        turn_start = time.monotonic()

        conversation = conversation.append_message("user", prompt)

        try:
            decision = should_dispatch(
                prompt,
                recent_messages=conversation.get_context_window(max_tokens=8_000),
                active_tasks=active_tasks,
                mode=mode,
            )
        except Exception as dispatch_err:
            log.warning("Dispatch classification failed, treating turn as conversational: %s", dispatch_err)
            decision = DispatchDecision(action="casual", reason="classifier_error")

        log.debug("Dispatch: %s -> %s (%s)", prompt[:40], decision.action, decision.reason)

        if _should_answer_background_status_directly(prompt, active_tasks):
            return await self._handle_background_status(
                session_id=session_id,
                conversation=conversation,
                prompt=prompt,
                dispatcher=dispatcher,
                turn_start=turn_start,
                active_tasks=active_tasks,
            )

        if background_ack_only:
            return await self._handle_background_ack(
                session_id=session_id,
                conversation=conversation,
                prompt=prompt,
                dispatcher=dispatcher,
                turn_start=turn_start,
            )

        if decision.action == "dispatch" and dispatch_actionable:
            return await self._handle_actionable(
                session_id=session_id,
                conversation=conversation,
                prompt=prompt,
                dispatcher=dispatcher,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
                turn_start=turn_start,
                images=images,
            )

        reply_kind = "casual" if decision.action == "casual" else "conversation"
        return await self._handle_casual(
            session_id=session_id,
            conversation=conversation,
            prompt=prompt,
            dispatcher=dispatcher,
            mode=mode,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            turn_start=turn_start,
            reply_kind=reply_kind,
            active_task_digest=active_task_digest,
        )

    async def _handle_background_status(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        turn_start: float,
        active_tasks: list[dict[str, Any]] | None = None,
    ) -> ConversationManager:
        final_text = _summarize_background_status(active_tasks)
        chunk_size = 80
        for i in range(0, len(final_text), chunk_size):
            await dispatcher.emit_text(final_text[i : i + chunk_size])

        conversation = conversation.append_message(
            "assistant",
            final_text,
            metadata={"specialists": ["reasoning"], "mode": "background_status"},
        )

        try:
            memory_coord = MemoryCoordinator(
                self.memory_engine,
                session_id,
                context_budget=_MODE_BUDGETS.get("fast", 1_500),
            )
            await memory_coord.capture_episode(
                turn_number=conversation.length // 2,
                user_message=prompt,
                assistant_response=final_text[:500],
                thinking="background_status",
                tool_calls=[],
                specialist="reasoning",
            )
        except Exception as exc:
            log.debug("Background status episode capture skipped: %s", exc)

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary="background_status",
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=0,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )

        return conversation

    async def _handle_background_ack(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        turn_start: float,
    ) -> ConversationManager:
        final_text = "Working on that now."
        await dispatcher.emit_text(final_text)

        conversation = conversation.append_message(
            "assistant",
            final_text,
            metadata={"specialists": ["reasoning"], "mode": "background_ack"},
        )

        try:
            memory_coord = MemoryCoordinator(
                self.memory_engine,
                session_id,
                context_budget=_MODE_BUDGETS.get("fast", 1_500),
            )
            await memory_coord.capture_episode(
                turn_number=conversation.length // 2,
                user_message=prompt,
                assistant_response=final_text,
                thinking="background_ack",
                tool_calls=[],
                specialist="reasoning",
            )
        except Exception as exc:
            log.debug("Background ack episode capture skipped: %s", exc)

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary="background_ack",
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=0,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )
        return conversation

    async def _handle_casual(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        turn_start: float,
        reply_kind: str = "casual",
        active_task_digest: str = "",
    ) -> ConversationManager:
        """Handle direct Thomas replies without visible delegation."""
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get("fast", 1_500),
        )

        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        if active_task_digest and _wants_background_status(prompt):
            memory_ctx.working = f"{memory_ctx.working}\n\n{active_task_digest}".strip()

        result = await self._dispatch_single(
            session_id=session_id,
            specialist_id="reasoning",
            prompt=prompt,
            conversation=conversation,
            memory_ctx=memory_ctx,
            dispatcher=dispatcher,
            thinking=ThinkingTracker(),
            mode=mode,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            stream_text_events=True,
        )

        final_text = result.content if result.ok else "Sorry, I had trouble with that."
        if not result.ok:
            chunk_size = 80
            for i in range(0, len(final_text), chunk_size):
                await dispatcher.emit_text(final_text[i : i + chunk_size])

        conversation = conversation.append_message(
            "assistant",
            final_text,
            metadata={"specialists": ["reasoning"], "mode": reply_kind},
        )

        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=final_text[:500],
            thinking=reply_kind,
            tool_calls=[],
            specialist="reasoning",
        )

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary=reply_kind,
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=result.tokens_used,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )

        return conversation

    async def _handle_actionable(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        turn_start: float,
        images: list[dict[str, Any]] | None = None,
    ) -> ConversationManager:
        """Handle actionable messages — acknowledge fast, dispatch work.

        Thomas immediately streams a quick acknowledgment so the user sees
        a response in milliseconds. Then the real work happens:

        1. Route to best specialist(s) via LLM classification
        2. Dispatch specialist work
        3. Stream results as they complete
        4. Thomas stays responsive for follow-up messages

        This is the core of the dispatch-first architecture.
        """
        thinking = ThinkingTracker()
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get(mode, 4_000),
        )

        # ── Immediately stream acknowledgment ─────────────────────
        # Thomas replies fast. The user sees this right away.
        # Keep it natural — not robotic. Acknowledge and stay open.
        await dispatcher.emit_text("Working on that — ")

        # ── Refresh memory (runs while user sees "On it.") ────────
        thinking.start(DelegationPhase.PLANNING.value)
        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        has_recalled_memory = bool(memory_ctx.episodic or memory_ctx.semantic)
        if has_recalled_memory:
            await dispatcher.emit_memory_refresh(
                layer="all",
                total_tokens=memory_ctx.total_tokens,
            )

        # ── Route to specialists ──────────────────────────────────
        thinking.append("Selecting best approach...")
        route = await self._classify_and_route(prompt, conversation, memory_ctx)
        thinking.append(f"Route: {route.reasoning}")
        thinking.end()

        for event in thinking.events():
            await dispatcher.emit(event)

        # ── Delegate to specialists ───────────────────────────────
        all_results: list[DelegationResult] = []
        specialists_used: list[str] = []

        if route.parallel and len(route.specialists) > 1:
            all_results = await self._dispatch_parallel(
                session_id=session_id,
                specialists=route.specialists,
                prompt=prompt,
                conversation=conversation,
                memory_ctx=memory_ctx,
                dispatcher=dispatcher,
                thinking=thinking,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
            )
        else:
            for specialist_id in route.specialists:
                result = await self._dispatch_single(
                    session_id=session_id,
                    specialist_id=specialist_id,
                    prompt=prompt,
                    conversation=conversation,
                    memory_ctx=memory_ctx,
                    dispatcher=dispatcher,
                    thinking=thinking,
                    mode=mode,
                    autonomy_level=autonomy_level,
                    token_economy=token_economy,
                )
                all_results.append(result)
                if result.ok:
                    specialists_used.append(specialist_id)

        # ── Synthesise response ───────────────────────────────────
        final_text = await self._synthesise(
            prompt=prompt,
            results=all_results,
            memory_ctx=memory_ctx,
            mode=mode,
        )

        # FIX (2026-03-18): Safety net — strip any leaked routing JSON from
        # the response. If the specialist or routing LLM accidentally returned
        # internal JSON (e.g. {"specialists":...}), remove it before streaming.
        if final_text:
            import re as _re

            final_text = _re.sub(
                r'\{"specialists"\s*:\s*\[.*?\]\s*,\s*"parallel"\s*:.*?\}',
                "",
                final_text,
            ).strip()

        # Stream the specialist's actual response
        chunk_size = 80
        for i in range(0, len(final_text), chunk_size):
            await dispatcher.emit_text(final_text[i : i + chunk_size])

        # Build full assistant message (acknowledgment + result)
        full_response = "Working on that — " + final_text

        # ── Update conversation ───────────────────────────────────
        conversation = conversation.append_message(
            "assistant",
            full_response,
            metadata={
                "specialists": specialists_used,
                "thinking_ms": thinking.total_ms,
                "mode": mode,
                "token_economy": str(token_economy or "optimal"),
            },
        )

        # ── Capture episode ───────────────────────────────────────
        tool_calls = []
        for r in all_results:
            tool_calls.extend(r.tool_calls)

        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=full_response[:500],
            thinking=thinking.total_text[:300],
            tool_calls=tool_calls,
            specialist=", ".join(specialists_used),
        )

        # ── Emit done ─────────────────────────────────────────────
        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary=thinking.summary(),
            total_thinking_ms=thinking.total_ms,
            iterations=sum(r.iterations for r in all_results),
            tool_calls=len(tool_calls),
            tokens_used=sum(r.tokens_used for r in all_results),
            specialists_used=specialists_used,
            total_elapsed_ms=elapsed,
        )

        return conversation

    # ── internal methods ─────────────────────────────────────────

    async def _classify_and_route(
        self,
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
    ) -> RouteDecision:
        """Use the brain's LLM to classify intent and decide routing.

        Falls back to the 'reasoning' specialist if classification fails.
        """
        available = self.registry.specialist_ids
        if not available:
            return RouteDecision(
                specialists=["reasoning"],
                reasoning="No specialists available; using default reasoning.",
            )

        if "tools" in available and _TOOLS_ROUTE_RE.search(str(prompt or "")):
            return RouteDecision(
                specialists=["tools"],
                parallel=False,
                reasoning="Deterministic tools route for explicit file or tool request.",
                confidence=0.98,
            )

        # Build routing prompt
        routing_prompt = self.registry.build_routing_prompt(prompt)

        try:
            # Ask the brain's LLM for a routing decision
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Thomas's orchestrator brain. Your job is to classify "
                        "the user's intent and route to the best specialist. "
                        "Available specialists are listed below. "
                        "Respond ONLY with valid JSON."
                    ),
                },
                {"role": "user", "content": routing_prompt},
            ]

            # Use the LLM for routing (fast mode, low token budget)
            response = await self._call_llm(messages, max_tokens=300)

            # Parse JSON response
            try:
                decision = json.loads(response)
                specialists = decision.get("specialists", [])
                # Validate specialist IDs exist
                specialists = [s for s in specialists if s in available]
                if not specialists:
                    specialists = [available[0]]

                return RouteDecision(
                    specialists=specialists,
                    parallel=decision.get("parallel", False),
                    reasoning=decision.get("reasoning", "LLM routing decision"),
                    confidence=decision.get("confidence", 0.8),
                )
            except (json.JSONDecodeError, KeyError):
                log.warning("Failed to parse routing response, using fallback")

        except Exception as exc:
            log.warning("Routing LLM call failed: %s", exc)

        # Fallback: use first available specialist
        fallback = "reasoning" if "reasoning" in available else available[0]
        return RouteDecision(
            specialists=[fallback],
            reasoning=f"Fallback routing to {fallback}",
            confidence=0.5,
        )

    async def _dispatch_single(
        self,
        session_id: str,
        specialist_id: str,
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
        dispatcher: EventDispatcher,
        thinking: ThinkingTracker,
        mode: str,
        autonomy_level: int,
        token_economy: str,
        stream_text_events: bool = False,
    ) -> DelegationResult:
        """Dispatch to a single specialist with contract + token."""
        specialist = self.registry.get(specialist_id)
        if specialist is None:
            return DelegationResult(
                specialist_id=specialist_id,
                status=SpecialistStatus.FAILED,
                error=f"Specialist '{specialist_id}' not found",
            )

        # Create contract
        contract = DelegationContract(
            specialist_id=specialist_id,
            task_description=prompt[:500],
            allowed_tools=specialist.capabilities,
            timeout_seconds=120,
            max_iterations=10,
            input_context={
                "memory": memory_ctx.to_system_injection(),
                "mode": mode,
                "token_economy": str(token_economy or "optimal"),
            },
        )

        # Issue capability token
        token = CapabilityToken(
            specialist_id=specialist_id,
            session_id=session_id,
            allowed_tools=specialist.capabilities,
            autonomy_level=autonomy_level,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        # Emit delegation event
        thinking.start(DelegationPhase.DELEGATING.value)
        thinking.append(f"Delegating to {specialist_id}...")
        await dispatcher.emit_delegation(
            specialist_id=specialist_id,
            task=prompt[:200],
            contract_id=contract.contract_id,
        )
        await dispatcher.emit_agent_activity(
            agent_id=specialist_id,
            status="running",
            current_task=prompt[:100],
        )

        # Execute specialist
        start = time.monotonic()
        result = DelegationResult(
            contract_id=contract.contract_id,
            specialist_id=specialist_id,
        )

        try:
            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            specialist_thinking: list[str] = []
            iterations = 0

            async for event in specialist.execute(
                contract=contract,
                token=token,
                prompt=prompt,
                conversation_context=conversation.get_context_window(max_tokens=8_000),
                memory_context=memory_ctx.to_system_injection(),
            ):
                event_type = event.get("type", "")

                # Pass through events to frontend
                if event_type == "text":
                    chunk = str(event.get("text", "") or "")
                    content_parts.append(chunk)
                    if stream_text_events and chunk:
                        await dispatcher.emit_text(chunk)
                elif event_type == "thinking":
                    specialist_thinking.append(event.get("text", ""))
                elif event_type in ("tool_start", "tool_result", "tool_args"):
                    await dispatcher.emit(event)
                    if event_type == "tool_result":
                        tool_calls.append(event)
                elif event_type == "done":
                    iterations = event.get("iterations", 0)
                elif event_type == "error":
                    result.error = event.get("error", "Unknown specialist error")

            elapsed = int((time.monotonic() - start) * 1000)
            result.content = "".join(content_parts)
            result.tool_calls = tool_calls
            result.thinking = "\n".join(specialist_thinking)
            result.elapsed_ms = elapsed
            result.iterations = iterations
            result.status = SpecialistStatus.COMPLETED if result.error is None else SpecialistStatus.FAILED

            # Validate output against contract
            thinking.start(DelegationPhase.VALIDATING.value)
            if contract.validate_output({"content": result.content}):
                thinking.append(f"{specialist_id} completed successfully ({elapsed}ms)")
            else:
                thinking.append(f"{specialist_id} output failed contract validation")
                result.status = SpecialistStatus.FAILED
            thinking.end()

        except asyncio.TimeoutError:
            result.status = SpecialistStatus.TIMEOUT
            result.error = f"Specialist {specialist_id} timed out after {contract.timeout_seconds}s"
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
        except Exception as exc:
            result.status = SpecialistStatus.FAILED
            result.error = str(exc)
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            log.error("Specialist %s failed: %s", specialist_id, exc)

        # Emit agent completion status
        await dispatcher.emit_agent_activity(
            agent_id=specialist_id,
            status=result.status.value,
            elapsed_ms=result.elapsed_ms,
        )

        self.registry.record_execution(specialist_id)
        thinking.end()

        return result

    async def _dispatch_parallel(
        self,
        session_id: str,
        specialists: list[str],
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
        dispatcher: EventDispatcher,
        thinking: ThinkingTracker,
        mode: str,
        autonomy_level: int,
        token_economy: str,
    ) -> list[DelegationResult]:
        """Dispatch to multiple specialists in parallel."""
        thinking.start(DelegationPhase.DELEGATING.value)
        thinking.append(f"Parallel dispatch to: {', '.join(specialists)}")
        thinking.end()

        tasks = [
            self._dispatch_single(
                session_id=session_id,
                specialist_id=sid,
                prompt=prompt,
                conversation=conversation,
                memory_ctx=memory_ctx,
                dispatcher=dispatcher,
                thinking=thinking,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
            )
            for sid in specialists
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[DelegationResult] = []
        for r in results:
            if isinstance(r, DelegationResult):
                final.append(r)
            elif isinstance(r, Exception):
                final.append(
                    DelegationResult(
                        status=SpecialistStatus.FAILED,
                        error=str(r),
                    )
                )
        return final

    async def _synthesise(
        self,
        prompt: str,
        results: list[DelegationResult],
        memory_ctx: MemoryContext,
        mode: str,
    ) -> str:
        """Synthesise specialist outputs into a coherent response.

        For single-specialist results, pass through directly.
        For multi-specialist results, use the brain's LLM to merge.
        """
        # Filter to successful results with actual content
        ok_results = [r for r in results if r.ok and r.content and r.content.strip()]

        if not ok_results:
            # All failed or produced empty content — build a helpful error
            errors = [r.error for r in results if not r.ok and r.error]
            if errors:
                return "I encountered issues processing your request. " + " ".join(errors[:3])
            # Edge case: specialist "succeeded" but returned empty content
            return (
                "I received your message but wasn't able to generate a response. "
                "Could you try rephrasing or asking in a different way?"
            )

        if len(ok_results) == 1:
            text = ok_results[0].content
            # Guard: if the specialist returned raw JSON (e.g. from a
            # confused model), don't pass it through as the response.
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed_json = json.loads(stripped)
                    # It IS valid JSON — the model responded with JSON
                    # instead of natural text. Try to extract useful content
                    # rather than showing the user a confusing error.
                    # FIX (2026-03-18): Previously returned "unexpected format"
                    # error. Now extracts text from JSON or passes through.
                    log.warning(
                        "Specialist returned raw JSON instead of text: %s",
                        stripped[:200],
                    )
                    # Try common response field names
                    if isinstance(parsed_json, dict):
                        for key in ("response", "content", "text", "answer", "message", "result"):
                            if key in parsed_json:
                                extracted = str(parsed_json[key]).strip()
                                if extracted:
                                    return extracted
                    # No extractable field — pass through the raw text
                    # (better than a dead-end error message)
                    return text
                except (ValueError, TypeError):
                    pass  # Not valid JSON — normal text that happens to start with {
            return text

        # Multiple results — synthesise with LLM
        parts = []
        for r in ok_results:
            parts.append(f"[{r.specialist_id}]: {r.content}")

        synthesis_prompt = (
            f"The user asked: {prompt[:300]}\n\n"
            f"Multiple specialists produced these results:\n\n"
            + "\n\n---\n\n".join(parts)
            + "\n\nSynthesise these into a single, coherent response."
        )

        try:
            messages = [
                {"role": "system", "content": "You synthesise multiple specialist outputs into one coherent response."},
                {"role": "user", "content": synthesis_prompt},
            ]
            return await self._call_llm(messages, max_tokens=2_000)
        except Exception as exc:
            log.warning("Synthesis LLM call failed: %s", exc)
            # Fallback: concatenate
            return "\n\n".join(r.content for r in ok_results)

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 1_000,
    ) -> str:
        """Call the brain's LLM (for routing, synthesis, etc.).

        Wraps Thomas's LLM client with error handling.
        Note: max_tokens is accepted for caller convenience but Thomas's
        LLMClient reads the limit from model config, not per-call args.
        """
        try:
            if hasattr(self.llm, "chat"):
                response = await self.llm.chat(messages=messages)
                # LLMClient.chat() returns a dict with "text" key
                if isinstance(response, dict):
                    return str(response.get("text", ""))
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)
            elif hasattr(self.llm, "complete"):
                prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                response = await self.llm.complete(prompt=prompt_text)
                return str(response)
            else:
                log.error("LLM client has no chat() or complete() method")
                return ""
        except Exception as exc:
            log.error("Brain LLM call failed: %s", exc)
            raise
