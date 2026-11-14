"""OrchestratorBrain — Thomas's model-owned conversation engine.

Every ordinary chat turn reaches Thomas's reasoning model. The model may
answer directly or invoke a structured capability such as ``send_task``;
deterministic code validates those calls but never infers intent from prose.

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

from thomas.agent.response_tone import strip_sandbox_links
from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.chat.thinking import ThinkingTracker
from thomas.core.autonomy import chat_delegation_directive
from thomas.marketplace.orchestrator.background_completions import (  # noqa: F401
    _COMPLETED_STATES,
    _FAILED_STATES,
    _FINISHED_STATES,
    _GENERIC_PROGRESS,
    _STATUS_ACTIVE_STATES,
    _STATUS_BUCKET_CAP,
    _STATUS_COMPLETED_STATES,
    _STATUS_FAILED_STATES,
    _bucket_background_rows,
    _build_completion_note,
    _collect_unreported_completions,
    _completion_delivery_line,
    _completion_detail,
    _displayed_completion_ids,
    _mark_completion_reported,
    _mark_completions_reported,
    _reported_completions,
    _summarize_background_status,
)
from thomas.marketplace.orchestrator.conversation_memory import memory_callbacks
from thomas.marketplace.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    DelegationPhase,
    DelegationResult,
    SpecialistStatus,
)
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.marketplace.orchestrator.response_failures import (
    _chat_failure_message,
    deliver_failure_text,
    egress_proxy_down,
    failing_target,
    ready_elsewhere,
)
from thomas.marketplace.specialists import final_pass as _final_pass

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
    ready_models:
        Reads the models that answered last check, for a failure that must name
        what to use instead (thomas/models/ready_elsewhere.py, passed in because
        the orchestrator may not import thomas.models). Without it nothing is named.
    """

    def __init__(
        self,
        config: Any,
        llm: Any,
        memory_engine: Any,
        registry: SpecialistRegistry,
        runtime_policy: Any = None,
        ready_models: Any = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.memory_engine = memory_engine
        self.registry = registry
        self.runtime_policy = runtime_policy
        self.ready_models = ready_models

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
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        display_prompt: str | None = None,
    ) -> ConversationManager:
        """Process one model-owned user turn.

        Thomas's reasoning model sees the conversation and structured task
        context, then chooses whether to answer or call a capability. No
        argument here selects a semantic route -- see CONTRIBUTING_AI.md,
        "Semantic Intent Ownership".
        """
        # is_first_message is caller state, not a control: it reports whether
        # this turn opens the thread and promises nothing about routing. The
        # brain does not need it (the same fact is readable off `conversation`),
        # but thomas/server/routes/chat_v2.py still passes it, so it stays
        # accepted until that caller drops it. Removing it here alone would
        # raise TypeError on every live chat turn.
        #
        # The two route-forcing arguments that used to sit beside it --
        # dispatch_actionable and background_ack_only -- are gone. They were
        # remains of the deleted prompt-word routing: the logic went, the
        # parameters stayed, so the signature advertised control it did not
        # provide (dispatch_actionable=False never prevented a dispatch).
        # Honouring them was not an open product choice. Both select a semantic
        # route before the model is consulted, which "Semantic Intent Ownership"
        # forbids, and no caller in thomas/ passed either -- the chat_v2 route
        # is pinned to never pass them by
        # test_auto_mode_low_autonomy_keeps_actionable_request_inline.
        _ = is_first_message
        turn_start = time.monotonic()

        # Private/project context may enrich the model prompt, but history must
        # preserve exactly what the user typed. Callers opt into a separate
        # display prompt so internal context never reappears as a user message.
        conversation = conversation.append_message("user", display_prompt if display_prompt is not None else prompt)

        # Compute any just-finished background work once, then make it model
        # context. This is factual state enrichment, not an intent classifier.
        # CRITICAL: only MARK a completion reported AFTER the chosen handler has
        # actually delivered it (the _mark_completions_reported calls below), never at
        # compute time — otherwise a branch that doesn't deliver would silently lose
        # the completion forever.
        fresh_completions = _collect_unreported_completions(session_id, active_tasks)
        completion_note = _build_completion_note(fresh_completions)

        conversation = await self._handle_casual(
            session_id=session_id,
            conversation=conversation,
            prompt=prompt,
            dispatcher=dispatcher,
            mode=mode,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            turn_start=turn_start,
            reply_kind="conversation",
            active_task_digest=active_task_digest,
            send_task=send_task,
            update_task=update_task,
            operate=operate,
            work_onboarding_update=work_onboarding_update,
            completion_note=completion_note,
            images=images,
        )
        _mark_completions_reported(session_id, fresh_completions)
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
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        completion_note: str = "",
        images: list[dict[str, Any]] | None = None,
    ) -> ConversationManager:
        """Handle direct Thomas replies without visible delegation."""
        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get("fast", 1_500),
            policy=getattr(self.runtime_policy, "memory", None),
        )

        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )
        # Always make the model aware of live background tasks whenever any exist (the
        # digest is only built when there ARE active tasks). This used to be gated behind
        # a status-intent regex, which left the model BLIND to its own running tasks on
        # any other phrasing — so "stop/cancel that task" found nothing to cancel and
        # Thomas falsely reported "nothing is running". Awareness is context, not a
        # keyword trigger: give it every turn and let the model decide organically whether
        # to steer, cancel, report on, or ignore the work. (chat sweep, 2026-06-27)
        if active_task_digest:
            memory_ctx.working = f"{memory_ctx.working}\n\n{active_task_digest}".strip()
        # When a background task just finished, make the MODEL aware of it by injecting
        # the note into its context, so it reports the result in its OWN words instead
        # of contradicting itself ("Quick update — finished" followed by "I don't have
        # the result back" — the exact bug from when the note was shown only to the
        # user, never to the model). The note text itself tells the model to relay the
        # worker's result without taking credit. Every visible reply stays model-authored
        # (your no-canned-replies rule); the deterministic line is reserved for the
        # non-model paths below (memory recall / model failure) where no model runs.
        if completion_note:
            memory_ctx.working = f"{memory_ctx.working}\n\n{completion_note}".strip()
        delivered_prefix = _completion_delivery_line(completion_note) if completion_note else ""

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
            send_task=send_task,
            update_task=update_task,
            operate=operate,
            work_onboarding_update=work_onboarding_update,
            images=images,
        )

        result_attempts = int(getattr(result, "attempts", 0) or 0)
        result_iterations = int(getattr(result, "iterations", 0) or 0)
        partial_text = result.content if result.content.strip() else ""
        if result.ok:
            # The model authored the reply (and, with the completion note in its
            # context above, the finished-work report is part of it). It already
            # streamed via the specialist — no canned prefix added.
            saved_text = result.content
            if not saved_text.strip() and delivered_prefix:
                # A tool-only turn reaches here with nothing to save. The work
                # still has to be reported: without this the turn is a blank
                # assistant message, which reads as "nothing happened" for a
                # run that finished the thing it was asked to do.
                await dispatcher.emit_text(delivered_prefix)
                saved_text = delivered_prefix
        else:
            # The model failed, so fall back to delivering any finished-work note
            # deterministically — a completed task must never be silently lost on an
            # error turn.
            turn_deadline_s = _final_pass.resolve_turn_deadline_s(getattr(self.runtime_policy, "tools", None))
            failure_text = _chat_failure_message(
                result.error,
                attempts=result_attempts,
                partial_output=bool(partial_text),
                autonomy_level=autonomy_level,
                turn_timeout_s=turn_deadline_s,
                proxy_down=await egress_proxy_down(result.error, target=failing_target(self.llm)),
                # A usage limit has to name what you can use instead, and only the catalog knows what answered.
                alternatives=await ready_elsewhere(self.ready_models, self.config, self.llm),
            )
            saved_text = await deliver_failure_text(
                dispatcher, delivered_prefix=delivered_prefix, failure_text=failure_text, partial_text=partial_text
            )
        conversation = conversation.append_message(
            "assistant",
            saved_text,
            metadata={"specialists": ["reasoning"], "mode": reply_kind},
        )

        result_tool_calls = list(getattr(result, "tool_calls", []) or [])
        await memory_coord.capture_episode(
            turn_number=conversation.length // 2,
            user_message=prompt,
            assistant_response=saved_text[:500],
            thinking=reply_kind,
            tool_calls=result_tool_calls,
            specialist="reasoning",
        )

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=conversation.version,
            thinking_summary=reply_kind,
            total_thinking_ms=0,
            iterations=result_iterations,
            attempts=result_attempts,
            tool_calls=len(result_tool_calls),
            tokens_used=result.tokens_used,
            specialists_used=["reasoning"],
            total_elapsed_ms=elapsed,
        )

        return conversation

    # ── internal methods ─────────────────────────────────────────

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
        send_task: Any = None,
        update_task: Any = None,
        operate: Any = None,
        work_onboarding_update: Any = None,
        images: list[dict[str, Any]] | None = None,
    ) -> DelegationResult:
        """Dispatch to a single specialist with contract + token."""
        specialist = self.registry.get(specialist_id)
        if specialist is None:
            return DelegationResult(
                specialist_id=specialist_id,
                status=SpecialistStatus.FAILED,
                error=f"Specialist '{specialist_id}' not found",
            )

        _remember_cb, _recall_cb = memory_callbacks(
            self.memory_engine, getattr(self.runtime_policy, "memory", None), session_id
        )

        # Create contract
        runtime_tools = getattr(self.runtime_policy, "tools", None)
        runtime_quality = getattr(self.runtime_policy, "quality", None)
        max_iterations = int(getattr(runtime_quality, "max_agent_iterations", 0) or 10)
        # Chat's reasoning specialist gets its own turn deadline, separate from
        # tool_timeout_s, leaving the final pass below its own reserve (I2).
        if specialist_id == "reasoning":
            turn_deadline_s = _final_pass.resolve_turn_deadline_s(runtime_tools)
            primary_timeout_s = _final_pass.primary_pass_timeout_s(turn_deadline_s)
        else:
            turn_deadline_s = None
            primary_timeout_s = float(getattr(runtime_tools, "tool_timeout_s", 120) or 120)
        contract = DelegationContract(
            specialist_id=specialist_id,
            task_description=prompt[:500],
            allowed_tools=specialist.capabilities,
            timeout_seconds=primary_timeout_s,
            max_iterations=max_iterations,
            input_context={
                "memory": memory_ctx.to_system_injection(),
                "mode": mode,
                "token_economy": str(token_economy or "optimal"),
                "system_instructions": str(getattr(self.runtime_policy, "instruction_context", lambda: "")() or ""),
                "profile_type": str(getattr(self.runtime_policy, "profile_type", "adaptive") or "adaptive"),
                "review_depth": str(getattr(self.runtime_policy, "review_depth", "adaptive") or "adaptive"),
                # The send_task callback (organic, no-regex dispatch). When present,
                # the reasoning model can hand work off via the send_task tool.
                "send_task": send_task,
                # The update_task callback: the model re-directs a RUNNING task (steer
                # or cancel), picking the right one by ref instead of a blind guess.
                "update_task": update_task,
                # Thomas's bounded direct-action callback. The server owns the
                # allowlist, policy runner, audit, and post-action readback proof.
                "operate": operate,
                # Work onboarding state is a model-authored structured call.
                # Browser/runtime code validates the envelope but never parses
                # either participant's prose to infer workflow state.
                "work_onboarding_update": work_onboarding_update,
                # Thomas's OWN memory — store/recall inline, never a task.
                "remember": _remember_cb,
                "recall": _recall_cb,
                # Autonomy reaches the MODEL here (not just the token): the level +
                # its ask-vs-hand-off directive, so "Max autonomy" actually changes
                # behavior instead of the model getting identical instructions at
                # every level. See thomas/core/autonomy.chat_delegation_directive.
                "autonomy": {
                    "level": int(autonomy_level),
                    "directive": chat_delegation_directive(autonomy_level),
                },
                "images": list(images or []),
            },
        )

        # Issue capability token. The reasoning specialist is Thomas's conversation
        # and control layer: it may read the repo, use Thomas-owned memory/task controls,
        # and call the bounded server-owned operator. It never receives raw write/shell
        # tools. Other specialists keep their declared capabilities.
        if specialist_id == "reasoning":
            allowed_tools = {
                "fs.read_file",
                "fs.list_dir",
                "fs.search",
                "skills.list",
                "skills.use",
                "send_task",
                "update_task",
                "remember",
                "recall",
                "operate",
            }
        else:
            allowed_tools = set(specialist.capabilities)
        if _remember_cb is None:
            allowed_tools.discard("remember")
        if _recall_cb is None:
            allowed_tools.discard("recall")
        token = CapabilityToken(
            specialist_id=specialist_id,
            session_id=session_id,
            allowed_tools=allowed_tools,
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

            # A provider can fail before producing a single token (for example a
            # transient local-model connection reset). One retry is safe only while
            # nothing visible or effectful has happened. This prevents a momentary
            # pre-output failure from becoming the opaque "Sorry" response while also
            # ensuring tools and partial answers are never replayed.
            for attempt in range(2):
                result.attempts = attempt + 1
                result.error = None
                content_parts = []
                tool_calls = []
                specialist_thinking = []
                iterations = 0
                retry_safe = True

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
                        if chunk:
                            retry_safe = False
                        if stream_text_events and chunk:
                            await dispatcher.emit_text(chunk)
                    elif event_type == "thinking":
                        specialist_thinking.append(event.get("text", ""))
                    elif event_type in ("tool_start", "tool_result", "tool_args"):
                        retry_safe = False
                        await dispatcher.emit(event)
                        if event_type == "tool_result":
                            tool_calls.append(event)
                    elif event_type in ("task_request", "task_update"):
                        # The real specialist's own send_task/update_task hand-off
                        # shape (never a tool_result) -- final_pass.already_acted
                        # needs to see it too, so it never repeats a hand-off (I4).
                        retry_safe = False
                        _final_pass.record_action_event(tool_calls, event)
                    elif event_type == "done":
                        iterations = event.get("iterations", 0)
                    elif event_type == "error":
                        result.error = event.get("error", "Unknown specialist error")
                    else:
                        # Any other unknown specialist event may represent a real
                        # side effect, so never replay after one.
                        retry_safe = False

                if result.error is not None and retry_safe and attempt == 0:
                    log.warning(
                        "Specialist %s failed before output; retrying once: %s",
                        specialist_id,
                        result.error,
                    )
                    await asyncio.sleep(0)
                    continue
                break

            if result.error is not None:
                log.error("Specialist %s returned an error: %s", specialist_id, result.error)

            elapsed = int((time.monotonic() - start) * 1000)
            # Drop broken sandbox/local-path links the model may have inlined
            # (e.g. [Download](sandbox:/mnt/data/x.pdf)); the real deliverable
            # ships as an attached artifact card.
            # Stripping is deliberately skipped on the error path: that text
            # already streamed to the screen verbatim, and rewriting it here
            # would leave saved history disagreeing with what was displayed.
            # A dead sandbox: link does survive on that path — the honest fix
            # is to stop emitting it upstream, which a post-hoc pass over a
            # token stream cannot do (a link can split across two chunks).
            joined_content = "".join(content_parts)
            result.content = strip_sandbox_links(joined_content) if result.error is None else joined_content
            result.tool_calls = tool_calls
            result.thinking = "\n".join(specialist_thinking)
            result.elapsed_ms = elapsed
            result.iterations = iterations
            if result.error is None:
                result.status = SpecialistStatus.COMPLETED
            elif any(token in str(result.error).lower() for token in ("timed out", "timeout")):
                result.status = SpecialistStatus.TIMEOUT
            else:
                result.status = SpecialistStatus.FAILED

            # final_pass.py: a timed-out pass gets exactly one more, with NO read
            # tools offered -- only send_task (level 3+, nothing effectful yet) or
            # nothing -- never "The selected model timed out ... try again."
            if result.status == SpecialistStatus.TIMEOUT and specialist_id == "reasoning":
                await _final_pass.run_final_pass(
                    result,
                    specialist=specialist,
                    contract=contract,
                    token=token,
                    prompt=prompt,
                    conversation=conversation,
                    memory_ctx=memory_ctx,
                    dispatcher=dispatcher,
                    stream_text_events=stream_text_events,
                    autonomy_level=autonomy_level,
                    start=start,
                    turn_deadline_s=turn_deadline_s,
                )
                elapsed = result.elapsed_ms

            # Validate output against contract
            thinking.start(DelegationPhase.VALIDATING.value)
            if result.error is not None:
                thinking.append(f"{specialist_id} ended with {result.status.value} ({elapsed}ms)")
            elif contract.validate_output({"content": result.content}):
                thinking.append(f"{specialist_id} completed successfully ({elapsed}ms)")
            elif result.tool_calls and not result.content.strip():
                # The contract asks for prose, and this turn has none — but the
                # tools ran and nothing errored, so the work happened. Calling
                # it FAILED here made _handle_casual replace the turn with "I
                # couldn't get an answer from the selected model", which is
                # untrue of a run that just created the task it was asked for.
                thinking.append(f"{specialist_id} acted through tools without closing prose ({elapsed}ms)")
            else:
                thinking.append(f"{specialist_id} output failed contract validation")
                result.status = SpecialistStatus.FAILED
            thinking.end()

        except asyncio.TimeoutError:
            result.attempts = max(1, result.attempts)
            result.status = SpecialistStatus.TIMEOUT
            result.error = f"Specialist {specialist_id} timed out after {contract.timeout_seconds}s"
            result.content = "".join(content_parts)
            result.tool_calls = tool_calls
            result.thinking = "\n".join(specialist_thinking)
            result.iterations = iterations
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
        except Exception as exc:
            result.attempts = max(1, result.attempts)
            result.status = SpecialistStatus.FAILED
            result.error = str(exc)
            result.content = "".join(content_parts)
            result.tool_calls = tool_calls
            result.thinking = "\n".join(specialist_thinking)
            result.iterations = iterations
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
        images: list[dict[str, Any]] | None = None,
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
                images=images,
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
