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
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.chat.thinking import ThinkingTracker
from thomas.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    DelegationPhase,
    DelegationResult,
    RouteDecision,
    SpecialistStatus,
)
from thomas.orchestrator.registry import SpecialistRegistry

log = logging.getLogger(__name__)

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
        images: list[dict[str, Any]] | None = None,
        is_first_message: bool = False,
    ) -> ConversationManager:
        """Process a user message through the full orchestration pipeline.

        This is the main entry point.  Flow:

        1. Refresh memory (all 3 layers)
        2. Classify intent → decide which specialists to invoke
        3. Create delegation contracts with capability tokens
        4. Dispatch to specialists (sequential or parallel)
        5. Validate specialist outputs against contracts
        6. Synthesise final response
        7. Update conversation (COW — returns new instance)
        8. Capture episode in memory

        Parameters
        ----------
        session_id:
            Current session identifier.
        conversation:
            Immutable ConversationManager (COW).
        prompt:
            User's message text.
        dispatcher:
            EventDispatcher for streaming events to frontend.
        mode:
            Execution mode (fast/auto/thinking/max).
        autonomy_level:
            1-4 autonomy level.

        Returns
        -------
        Updated ConversationManager with user + assistant messages appended.
        """
        turn_start = time.monotonic()
        thinking = ThinkingTracker()
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get(mode, 4_000),
        )

        # ── Step 1: Append user message ──────────────────────────
        conversation = conversation.append_message("user", prompt)

        # ── Step 2: Refresh memory ───────────────────────────────
        thinking.start(DelegationPhase.PLANNING.value)
        thinking.append("Refreshing memory layers...")

        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        # Only show memory badge when episodic or semantic memory was
        # actually retrieved — working memory is always populated from
        # the conversation so it shouldn't trigger the badge by itself.
        has_recalled_memory = bool(memory_ctx.episodic or memory_ctx.semantic)
        if has_recalled_memory:
            await dispatcher.emit_memory_refresh(
                layer="all",
                total_tokens=memory_ctx.total_tokens,
            )
            thinking.append(
                f"Retrieved {memory_ctx.total_tokens} tokens of context "
                f"(working + episodic + semantic)."
            )

        # ── Step 3: Classify intent & route ──────────────────────
        thinking.append("Classifying intent and selecting specialists...")
        route = await self._classify_and_route(prompt, conversation, memory_ctx)
        thinking.append(f"Route decision: {route.reasoning}")
        thinking.append(f"Specialists: {', '.join(route.specialists)}")
        thinking.end()

        # Emit thinking events
        for event in thinking.events():
            await dispatcher.emit(event)

        # ── Step 4: Delegate to specialists ──────────────────────
        all_results: list[DelegationResult] = []
        specialists_used: list[str] = []

        if route.parallel and len(route.specialists) > 1:
            # Parallel dispatch
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
            )
        else:
            # Sequential dispatch
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
                )
                all_results.append(result)
                if result.ok:
                    specialists_used.append(specialist_id)

        # ── Step 5: Synthesise response ──────────────────────────
        thinking.start(DelegationPhase.SYNTHESIZING.value)
        thinking.append("Synthesising specialist outputs into final response...")

        final_text = await self._synthesise(
            prompt=prompt,
            results=all_results,
            memory_ctx=memory_ctx,
            mode=mode,
        )
        thinking.end()

        # First-message capability hint (only once per session)
        if is_first_message and final_text:
            final_text += (
                "\n\n---\n*I can also run code, search the web, manage files, "
                "and coordinate multiple agents on complex tasks. Just ask.*"
            )

        # Stream the final response text
        # Split into chunks for smooth streaming
        chunk_size = 80
        for i in range(0, len(final_text), chunk_size):
            chunk = final_text[i : i + chunk_size]
            await dispatcher.emit_text(chunk)

        # ── Step 6: Update conversation ──────────────────────────
        conversation = conversation.append_message(
            "assistant",
            final_text,
            metadata={
                "specialists": specialists_used,
                "thinking_ms": thinking.total_ms,
                "mode": mode,
            },
        )

        # ── Step 7: Capture episode ──────────────────────────────
        tool_calls = []
        for r in all_results:
            tool_calls.extend(r.tool_calls)

        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=final_text[:500],
            thinking=thinking.total_text[:300],
            tool_calls=tool_calls,
            specialist=", ".join(specialists_used),
        )

        # ── Step 8: Emit done ────────────────────────────────────
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
                    content_parts.append(event.get("text", ""))
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
                    json.loads(stripped)
                    # It IS valid JSON — the model responded with JSON
                    # instead of natural text.  This is a model error.
                    log.warning(
                        "Specialist returned raw JSON instead of text: %s",
                        stripped[:200],
                    )
                    return (
                        "I received your message but my response came back "
                        "in an unexpected format. Could you try again?"
                    )
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
