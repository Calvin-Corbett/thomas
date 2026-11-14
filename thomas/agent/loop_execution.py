"""Main agent loop execution and event streaming."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from thomas.agent import loop_anchors as anchors
from thomas.agent import loop_interrupts as steers
from thomas.agent.acceptance_runtime import hold_at_finish
from thomas.agent.checkin_policy import resolve_checkin_policy
from thomas.agent.constraint_envelope import ConstraintEnvelope, envelope_events
from thomas.agent.hook_events import HookEvent, emit_hook
from thomas.agent.loop_completion import handle_post_loop_completion
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_execution_setup import prepare_execution_setup
from thomas.agent.loop_helpers import (
    _coerce_async_iterator,
    _ensure_llm_hardened_client,
    _validate_benchmark_code_output,
    httpx_ConnectError,
)
from thomas.agent.loop_provider_runtime import (
    TPM_WAIT_SLICE_SECONDS,
    ProviderPromptWindow,
    compact_conversation_if_needed,
    connection_error_message,
)

# Compatibility re-exports: callers historically imported these helpers here.
from thomas.agent.loop_tool_protocol import (  # noqa: F401
    _MAX_TOOL_RESULT_CHARS,
    _canonical_code_tool_name,
    _code_tool_action,
    _failed_tool_signature,
    _is_code_mutation_name,
    _record_failed_tool,
    _shell_command_is_mutation,
    _tool_result_with_recovery,
    _tool_spec_name,
)
from thomas.agent.loop_turn_context import build_turn_messages, context_breakdown_of, prepare_turn_context
from thomas.agent.tool_result_cap import cap_tool_result, sandbox_root_of
from thomas.core import capture_context
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMError
from thomas.core.llm_shared import callable_accepts_keyword
from thomas.marketplace.observability import derive_messages as honesty_shadow

if TYPE_CHECKING:
    from thomas.agent.loop import AgentLoop

log = logging.getLogger(__name__)

_TPM_WAIT_SLICE_SECONDS = TPM_WAIT_SLICE_SECONDS
_connection_error_message = connection_error_message


async def _agent_loop_run(
    self: AgentLoop,
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

    The loop:
    1. Build messages with context window management
    2. Stream LLM response, yielding tokens to caller in real-time
    3. If tool calls detected, execute them (parallel when independent)
    4. Append tool results, loop back to LLM
    5. Stop on: no tool calls, max iterations, context overflow, or error
    """
    setup = prepare_execution_setup(
        self,
        prompt,
        intent_text=intent_text,
        mode=mode,
        tools_policy=tools_policy,
        token_economy=token_economy,
        max_iterations=max_iterations,
        job_type=job_type,
    )
    prompt_text = setup.prompt_text
    request_text = setup.request_text
    routing_text = setup.routing_text
    benchmark_mode = setup.benchmark_mode
    current_job_type = setup.current_job_type
    route = setup.route
    route_input_source = setup.route_input_source
    autonomy_name = setup.autonomy_name
    effective_mode = setup.effective_mode
    applied_token_economy = setup.applied_token_economy
    token_economy_meta = setup.token_economy_meta
    strict_issue_ownership = setup.strict_issue_ownership
    best_practice_gate_active = setup.best_practice_gate_active
    best_practice_gate_source = setup.best_practice_gate_source
    code_output_validation_enabled = setup.code_output_validation_enabled
    runtime_skills_payload = setup.runtime_skills_payload
    usage_before = setup.usage_before
    stream_usage = setup.stream_usage
    max_iter = setup.max_iter
    # The model owns whether to answer, clarify, or call a capability.  These
    # counters remain in receipts for compatibility but no prose classifier
    # triggers hidden clarification rewrites.
    clarification_question_cap = 0
    full_auto_reprompt_count = 0
    clarification_questions_asked = 0
    clarification_reprompt_count = 0
    effective_tools_policy = setup.effective_tools_policy
    tool_specs = setup.tool_specs
    preserve_first = setup.preserve_first
    preserve_last = setup.preserve_last
    history_token_cap = setup.history_token_cap
    state = LoopState()
    iter_token_estimates: list[int] = []
    cumulative_context_tokens = 0
    peak_context_tokens = 0
    tool_chars_total = 0
    tool_chars_kept = 0
    iter_prompt_spends: list[int] = []
    high_prompt_spend_fail_iters = 0
    code_output_guard_reprompts = 0
    code_output_guard_last_issue = ""
    followup_suppressed_count = 0
    thought_leak_suppressed_count = 0
    quality_tool_events: list[dict[str, Any]] = []
    failure_counts: dict[str, int] = {}
    repeated_failure_count = 0
    code_mutation_seen = False
    pre_edit_inspections = 0
    post_edit_inspections = 0
    runaway_guard_reason: str | None = None
    mode_context_budget = setup.mode_context_budget
    hard_context_budget = setup.hard_context_budget
    emergency_context_budget = setup.emergency_context_budget
    iter_prompt_warn_cap = setup.iter_prompt_warn_cap
    iter_prompt_hard_cap = setup.iter_prompt_hard_cap
    provider_tpm_limit = setup.provider_tpm_limit
    provider_tpm_budget = setup.provider_tpm_budget
    provider_prompt_tracker = ProviderPromptWindow(provider_tpm_budget)
    provider_prompt_window = provider_prompt_tracker.entries
    provider_tpm_wait_events = 0
    provider_tpm_wait_seconds = 0.0
    provider_prompt_tokens_last_minute = 0
    stream_prompt_prev = 0

    yield AgentEvent(
        type=EventType.AGENT_START,
        data={
            "prompt": request_text,
            "route": route.to_dict(),
            "route_input_source": route_input_source,
            "mode": effective_mode,
            "tools_policy": effective_tools_policy,
            "autonomy_level": int(self._autonomy_level),
            "autonomy_name": autonomy_name,
            "token_economy": token_economy_meta,
            "library_enabled": bool(self._library is not None),
            "skills": dict(runtime_skills_payload),
            "history_policy": {
                "preserve_first": int(preserve_first),
                "preserve_last": int(preserve_last),
                "history_token_cap": int(history_token_cap),
            },
        },
    )

    prepare_turn_context(self, setup, quality_retry_count=_quality_retry_count)
    memory_text = setup.memory_text
    continuity_hint = setup.continuity_hint
    test_visibility_hint = setup.test_visibility_hint
    memory_tokens = setup.memory_tokens
    anchors.pin_turn_request(self, prompt, quality_retry=int(_quality_retry_count) > 0)
    turn_user_content: Any = prompt

    # Mid-run check-in policy (CAP-051): zero overhead unless configured.
    checkin_policy = getattr(self, "_checkin_policy", None) or resolve_checkin_policy(self.config)
    if checkin_policy is not None:
        self._checkin_policy = checkin_policy

    # Constraint envelope (CAP-048) is inert unless configured via env.
    constraint_envelope = ConstraintEnvelope.from_env()

    iteration = 0
    while iteration < max_iter:
        if (run_hold := getattr(self, "run_hold", None)) is not None:  # Build's pause; absent everywhere else
            await run_hold(iteration)
        if (drain_signal := os.environ.get("THOMAS_CODE_RELOAD_DRAIN_SIGNAL")) and os.path.isfile(drain_signal):
            yield AgentEvent.status("Yielding unfinished Build run for landed-code reload.", iteration=iteration)
            return
        state.iteration = iteration
        iteration += 1

        # Auto-compact conversation if approaching token budget.
        # This runs before _build_messages to avoid hard truncation.
        if iteration >= 1:
            await compact_conversation_if_needed(self, preserve_last=preserve_last, setup=setup)

        iteration_preserve_first = preserve_first
        iteration_preserve_last = preserve_last
        if self._last_compaction_result is not None:
            iteration_preserve_first = len(self._conversation)
            iteration_preserve_last = len(self._conversation)

        # Build messages with context window management; inject memory only once.
        mem = ""
        if state.iteration == 0:
            context_parts = (memory_text, continuity_hint, test_visibility_hint)  # memory_text holds the library.
            mem = "\n\n".join(part for part in context_parts if part)
        # The model keeps every tool for the whole run. Thomas used to strip the
        # read tools after 6 inspections, and ALL tools after 6 post-edit reads, so
        # the one action most likely to catch a mistake -- re-reading what you just
        # wrote -- was removed precisely when it mattered.
        iteration_tool_specs = tool_specs
        messages, budget_stop = build_turn_messages(
            self,
            state,
            setup,
            memory_text=mem,
            preserve_first=iteration_preserve_first,
            preserve_last=iteration_preserve_last,
            iteration=iteration,
        )
        if budget_stop is not None:
            yield budget_stop
            break
        iter_token_estimates.append(int(state.token_estimate))
        cumulative_context_tokens += int(state.token_estimate)
        peak_context_tokens = max(peak_context_tokens, int(state.token_estimate))
        # Defense-in-depth: shadow_diff_if_enabled already guards its own body
        # with this same named tuple, but a zero-effect diagnostic must not be
        # able to kill a live turn even via a bug outside that inner try --
        # matching the neighboring auto-compact block's non-fatal pattern.
        try:
            honesty_shadow.shadow_diff_if_enabled(self._run_id, messages)
        except honesty_shadow.SHADOW_EXCEPTIONS as _shadow_err:
            honesty_shadow.shadow_diff_failures += 1
            log.debug("Shadow diff call site failed (non-fatal): %s", _shadow_err)

        if provider_tpm_budget > 0:
            while True:
                next_prompt_estimate = int(state.token_estimate)
                if provider_prompt_window:
                    next_prompt_estimate = max(
                        next_prompt_estimate,
                        provider_prompt_tracker.observed_average(),
                    )
                projected_usage = provider_prompt_tracker.projected_wait_seconds(next_prompt_estimate)
                wait_s, projected_prompt, current_prompt = projected_usage
                provider_prompt_tokens_last_minute = int(current_prompt)
                if wait_s <= 0:
                    break
                if next_prompt_estimate > provider_tpm_budget:
                    yield AgentEvent.status(
                        (
                            "This request exceeds the optional local TPM estimate; "
                            "Thomas is deferring enforcement to the provider instead of stopping the task."
                        ),
                        iteration=iteration,
                    )
                    break
                sleep_s = min(float(wait_s), _TPM_WAIT_SLICE_SECONDS)
                provider_tpm_wait_events += 1
                provider_tpm_wait_seconds += sleep_s
                yield AgentEvent.status(
                    (
                        f"Pausing {sleep_s:.1f}s for the explicitly configured provider rate policy "
                        f"({projected_prompt:,}/{provider_tpm_budget:,} estimated prompt tokens/min)."
                    ),
                    iteration=iteration,
                )
                await asyncio.sleep(sleep_s)

        yield AgentEvent(
            type=EventType.AGENT_ITERATION,
            data={
                "iteration": iteration,
                "message_count": len(messages),
                "token_estimate": state.token_estimate,
                "context_window": self._context_window,
                "context_window_profile": str(self.llm.config.name or "").strip().lower(),
                "context_breakdown": context_breakdown_of(messages, state.token_estimate),
            },
            iteration=iteration,
        )

        # Collect this iteration's response
        text_chunks: list[str] = []
        pending_tool_calls: list[dict[str, Any]] = []
        iter_prompt_start_total = int(stream_usage.get("prompt_tokens", 0) or 0)

        # Hook surface (model category): fires immediately before the LLM call.
        # Read-only this release (return value ignored); never breaks the turn.
        await emit_hook(
            self,
            HookEvent.MODEL_CALL,
            {"messages": messages, "model": str(getattr(self.llm.config, "model", "") or "")},
        )

        # Honesty-spine correlation: tag every model call this turn's LLM
        # client makes with the AgentLoop's own run_id, so the capture hook
        # in LLMClient.stream_chat lands under the run this turn belongs to
        # instead of falling back to the uncorrelated ambient run. Scoped
        # tightly around the model-call try/except below; reset unconditionally.
        _capture_token = capture_context.set_capture_run(self._run_id)
        try:
            llm_stream_error: str | None = None
            await _ensure_llm_hardened_client(self.llm)
            stream_chat_kwargs = (
                {"turn_user_content": turn_user_content}
                if callable_accepts_keyword(self.llm.stream_chat, "turn_user_content")
                else {}
            )
            llm_stream = await _coerce_async_iterator(
                self.llm.stream_chat(messages, iteration_tool_specs, **stream_chat_kwargs),
                source="LLMClient.stream_chat",
            )

            async for event in llm_stream:
                if event.type == "thinking":
                    # Forward thinking/reasoning tokens to the stream
                    yield AgentEvent(
                        type=EventType.THINKING,
                        data={"text": event.data.get("text", "")},
                        iteration=iteration,
                    )
                elif event.type == "token":
                    text = event.data.get("text", "")
                    text_chunks.append(text)

                elif event.type == "tool_call_start":
                    tc_id = event.data.get("id", "")
                    tc_name = event.data.get("name", "")
                    yield AgentEvent.tool_call_start(tc_id, tc_name, iteration=iteration)

                elif event.type == "tool_call_delta":
                    tc_id = event.data.get("id", "")
                    delta = event.data.get("delta", "")
                    if tc_id and delta:
                        yield AgentEvent.tool_call_args_delta(tc_id, delta, iteration=iteration)

                elif event.type == "tool_call_end":
                    tc_data = {
                        "id": event.data.get("id", ""),
                        "name": event.data.get("name", ""),
                        "arguments": event.data.get("arguments", ""),
                    }
                    pending_tool_calls.append(tc_data)
                    yield AgentEvent.tool_call_end(tc_data["id"], tc_data["arguments"], iteration=iteration)

                elif event.type == "error":
                    # Some providers surface errors as stream events.
                    err = str(event.data.get("error", "")).strip() or "LLM error"
                    llm_stream_error = err
                    yield AgentEvent.agent_error(err, iteration=iteration)

                elif event.type == "done":
                    if event.data.get("model"):  # what the provider says answered (build_model_receipt.py)
                        yield AgentEvent.model_reported(str(event.data["model"]), iteration=iteration)
                    # Don't `break` here: exiting an `async for` early triggers an
                    # `aclose()` on the underlying async generator while it's still
                    # unwinding network I/O, which can produce noisy asyncio/httpx
                    # shutdown errors. Let it terminate naturally on StopAsyncIteration.
                    continue

                elif event.type == "usage":
                    usage_part = self._usage_from_event_payload(event.data.get("usage"))
                    stream_usage = self._normalize_usage(
                        stream_usage["prompt_tokens"] + usage_part["prompt_tokens"],
                        stream_usage["completion_tokens"] + usage_part["completion_tokens"],
                        stream_usage["total_tokens"] + usage_part["total_tokens"],
                    )

            if llm_stream_error:
                state.error = llm_stream_error
                state.finished = True
                break

        except LLMError as e:
            error_msg = str(e)
            if int(getattr(e, "status", 0) or 0) == 429 and not e.quota_hint and iteration + 1 < max_iter:
                remaining_fn = getattr(self.llm, "_rate_limit_remaining", None)
                remaining = 0.0
                if callable(remaining_fn):
                    try:
                        remaining = max(0.0, float(remaining_fn(self.llm.config) or 0.0))
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        remaining = 0.0
                while remaining > 0:
                    sleep_s = min(remaining, _TPM_WAIT_SLICE_SECONDS)
                    yield AgentEvent.status(
                        f"The provider asked Thomas to pause for {sleep_s:.1f}s; work will resume automatically.",
                        iteration=iteration,
                    )
                    await asyncio.sleep(sleep_s)
                    if callable(remaining_fn):
                        try:
                            remaining = max(0.0, float(remaining_fn(self.llm.config) or 0.0))
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            remaining = max(0.0, remaining - sleep_s)
                    else:
                        remaining = max(0.0, remaining - sleep_s)
                yield AgentEvent.status("Provider rate limit cleared; resuming this task.", iteration=iteration)
                continue
            # Detect connection errors and give a helpful message
            if "connect" in error_msg.lower() or "refused" in error_msg.lower():
                error_msg = _connection_error_message(self.llm)
            yield AgentEvent(
                type=EventType.AGENT_ERROR,
                data={
                    "error": error_msg,
                    "status": int(getattr(e, "status", 0) or 0),
                    "retryable": bool(getattr(e, "retryable", False)),
                    "error_code": str(getattr(e, "error_code", "") or ""),
                    "response_headers": dict(getattr(e, "response_headers", {}) or {}),
                },
                iteration=iteration,
            )
            state.error = error_msg
            state.finished = True
            break

        except (httpx_ConnectError, ConnectionError, OSError):
            error_msg = _connection_error_message(self.llm)
            yield AgentEvent.agent_error(error_msg, iteration=iteration)
            state.error = error_msg
            state.finished = True
            break

        finally:
            capture_context.reset(_capture_token)

        # Accumulate text response
        iter_text = "".join(text_chunks)
        iter_text, suppressed = self._sanitize_assistant_text(
            iter_text,
            prompt_text=routing_text,
            route=route,
            route_input_source=route_input_source,
            pending_tool_calls=len(pending_tool_calls),
        )
        if suppressed:
            followup_suppressed_count += 1
        if self._last_sanitize_flags.get("thought_leak"):
            thought_leak_suppressed_count += 1
        if iter_text.strip() == "Understood. How can I assist you further?":
            iter_text = "I didn't answer that. Please ask a specific question."

        if iter_text:
            yield AgentEvent.text_delta(iter_text, iteration=iteration)

        if provider_tpm_budget > 0:
            stream_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
            stream_prompt_delta = max(0, stream_prompt_now - stream_prompt_prev)
            if stream_prompt_delta > 0:
                stream_prompt_prev = stream_prompt_now
                provider_prompt_tokens_last_minute = provider_prompt_tracker.record(stream_prompt_delta)
            elif stream_prompt_now > stream_prompt_prev:
                stream_prompt_prev = stream_prompt_now

        iter_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
        iter_prompt_spend = max(0, iter_prompt_now - int(iter_prompt_start_total))
        iter_prompt_spends.append(int(iter_prompt_spend))

        envelope_decision = constraint_envelope.observe(int(stream_usage.get("total_tokens", 0) or 0))
        for envelope_event in envelope_events(envelope_decision, iteration=iteration):
            yield envelope_event
        if envelope_decision.should_stop:
            state.error = envelope_decision.stop_message
            state.finished = True
            break

        benchmark_validation_ok = True
        benchmark_issue = ""
        if str(job_type or "").strip().lower() == "benchmark" and code_output_validation_enabled:
            benchmark_validation_ok, benchmark_issue, _ = _validate_benchmark_code_output(
                prompt_text=routing_text,
                continuation=iter_text,
            )
        if not benchmark_validation_ok:
            code_output_guard_reprompts += 1
            code_output_guard_last_issue = str(benchmark_issue or "")
            if (iteration + 1) < max_iter:
                guard_context = str(routing_text or "").strip().replace("\n", " ")
                if guard_context:
                    user_prompt = (
                        f"Original request: {guard_context}\n"
                        "Previous continuation failed code-output validation: "
                        f"{code_output_guard_last_issue}. "
                        "Return only valid Python continuation code meeting code-output requirements."
                    )
                else:
                    user_prompt = (
                        "Previous continuation failed code-output validation: "
                        f"{code_output_guard_last_issue}. "
                        "Return only valid Python continuation code meeting code-output requirements."
                    )
                anchors.add_steering(self, user_prompt)
                turn_user_content = user_prompt
                continue
            issue_error = f"Code-output guard blocked completion: {code_output_guard_last_issue}".strip()
            state.error = issue_error
            yield AgentEvent.agent_error(issue_error, iteration=iteration)
            state.finished = True
            break

        state.aggregate_response += iter_text

        # A steer can arrive while the model is composing its final answer, with no tool call left to trigger the
        # between-tools check below: it gets another iteration in THIS run, never left queued and unread.
        steer_kind, steer = steers.read_queued_steer(None if pending_tool_calls else self._message_queue)
        if steer_kind == steers.STOP:
            yield steers.stopped_by_you(state, iteration)
            break
        if steer_kind == steers.TEXT:
            anchors.add_amendment(self, steer, reply=iter_text)
            turn_user_content, max_iter = steer, steers.turn_for_steer(iteration, max_iter)
            yield AgentEvent.status("Received your update. Continuing this task.", iteration=iteration)
            continue

        # If no tool calls, we're done - unless the acceptance contract says the
        # text was commentary: then its gaps become the next user turn of this
        # same loop and the model keeps working (a text reply is never "done").
        if not pending_tool_calls:
            hold_text = await hold_at_finish(self, response_text=iter_text, tool_events=quality_tool_events)
            if hold_text:
                if iter_text:
                    self._conversation.append({"role": "assistant", "content": iter_text})
                anchors.add_steering(self, hold_text)
                turn_user_content = hold_text
                yield AgentEvent.status(
                    "Reply checked against the acceptance contract: not finished yet.", iteration=iteration
                )
                continue
            if iter_text:
                # Keep the user-facing handoff separate from prose emitted while
                # tools were still running. ``aggregate_response`` retains the
                # complete internal transcript without becoming one giant reply.
                state.text_response = iter_text
                self._conversation.append({"role": "assistant", "content": iter_text})
                if not benchmark_mode:
                    self._record_event("assistant_response", iter_text)
            # Hook surface (completion category): fires at end-of-turn once the
            # final assistant text is finalized. Read-only this release.
            await emit_hook(self, HookEvent.COMPLETION, {"text": state.text_response})
            state.finished = True
            break

        # Build assistant message with tool calls for the message history
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": iter_text or ""}
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
            for tc in pending_tool_calls
        ]
        self._conversation.append(assistant_msg)

        # Execute tool calls (parallel when multiple), streaming each completion.
        # A provider may emit dozens of calls in one response, so enforce the
        # inspection budget before scheduling the batch rather than after every
        # task has already run. Refused calls still receive tool-result messages,
        # preserving a valid provider history without the 35-call log avalanche.
        # Every requested call is executed. A call over an inspection budget used to
        # be dropped and returned as a tool result with ok=False -- telling the model
        # its tool FAILED when it had simply never been attempted. Teaching a model
        # something false about its own environment is the worst version of this bug.
        execution_tool_calls = pending_tool_calls

        tool_results: list[AgentEvent] = []
        tool_results_by_id: dict[str, AgentEvent] = {}
        batch_amendments: list[dict[str, Any]] = []

        async def _bounded_tool_results() -> AsyncIterator[AgentEvent]:
            async for executed in self._execute_tools(execution_tool_calls, iteration):
                yield executed

        async for result_event in _bounded_tool_results():
            tc_id = str(result_event.data.get("tool_id", ""))
            tc: dict[str, Any] = {}
            for maybe_tc in pending_tool_calls:
                if str(maybe_tc.get("id", "")) == tc_id:
                    tc = maybe_tc
                    break
            matched_tool_call = bool(tc)
            if not tc:
                tc = {"id": tc_id, "name": result_event.data.get("tool_name", "tool"), "arguments": "{}"}

            parsed_args, _parse_err = self._parse_tool_args(tc.get("arguments"))
            # The worker's completion receipt identifies the invocation that ran.
            result_event.data["arguments"] = parsed_args if matched_tool_call else None
            yield result_event
            tool_results.append(result_event)
            tool_results_by_id[tc_id] = result_event

            args_meta = parsed_args if isinstance(parsed_args, dict) else {}
            quality_tool_events.append(
                {
                    "name": str(tc.get("name") or ""),
                    "ok": bool(result_event.data.get("ok", False)),
                    "command": str(args_meta.get("command") or args_meta.get("cmd") or args_meta.get("shell") or "")[
                        :2000
                    ],
                    "path": str(args_meta.get("path") or args_meta.get("file") or args_meta.get("filename") or "")[
                        :500
                    ],
                    "output_preview": str(
                        result_event.data.get("result_text") or result_event.data.get("result") or ""
                    )[:2000],
                }
            )

            # Truncate tool results that would dominate context
            result_text = str(result_event.data.get("result_text", ""))
            if not result_event.data.get("ok"):
                result_text = _tool_result_with_recovery(str(tc.get("name") or ""), result_text)
            original_len = len(result_text)
            result_text = cap_tool_result(  # head + tail; the full text is saved where fs.read_file reaches it
                result_text, _MAX_TOOL_RESULT_CHARS, tool_name=str(tc.get("name") or ""), call_id=str(tc_id),
                sandbox_root=sandbox_root_of(self), run_id=str(getattr(self, "_run_id", "") or ""),
            )  # fmt: skip
            tool_chars_total += original_len
            tool_chars_kept += len(result_text)

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            }
            anchors.store_tool_result(self._conversation, tool_msg, batch_amendments)
            if (run_hold := getattr(self, "run_hold", None)) is not None:
                await run_hold(iteration)

            # ── message interruption check ── Between tool completions, a message from you stops the run
            # or joins it: the next iteration routes against the updated request (loop_interrupts).
            steer_kind, steer = steers.read_queued_steer(self._message_queue)
            if steer_kind == steers.STOP:
                yield steers.stopped_by_you(state, iteration)
                break
            if steer_kind == steers.TEXT:
                anchors.add_amendment(self, steer, batch=batch_amendments)
                turn_user_content, max_iter = steer, steers.turn_for_steer(iteration, max_iter)
                yield steers.adapting(iteration)

            state.total_tool_calls += 1

            if checkin_policy is not None:
                for checkin in checkin_policy.observe_step(
                    total_tokens=int(stream_usage.get("total_tokens", 0) or 0),
                    label=str(tc.get("name") or ""),
                ):
                    yield AgentEvent(
                        type=EventType.STATUS,
                        data={"message": checkin.message, "checkin": checkin.to_dict()},
                        iteration=iteration,
                    )
                    if checkin.ack_required:
                        await checkin_policy.wait_until_acknowledged()

            tool_action = _code_tool_action(str(tc.get("name") or ""), args_meta)
            if tool_action == "mutation" and result_event.data.get("ok"):
                self._tool_failure_guard.reset_after_mutation(failure_counts)
            if current_job_type == "coding":
                if tool_action == "mutation" and result_event.data.get("ok"):
                    code_mutation_seen = True
                    post_edit_inspections = 0
                elif code_mutation_seen and tool_action == "inspection":
                    post_edit_inspections += 1
                elif tool_action == "inspection":
                    pre_edit_inspections += 1

            # Stop only an identical failing call, not different failures from
            # the same multi-purpose tool.
            if result_event.data.get("budget_refusal"):
                repeated_failure_count = 0
            elif not result_event.data.get("ok"):
                repeated_failure_count = _record_failed_tool(
                    failure_counts, str(tc.get("name") or ""), parsed_args or {}, result_text
                )
            else:
                repeated_failure_count = 0

            if repeated_failure_count >= 3:
                yield AgentEvent.agent_error(
                    "Tool loop stability issue: "
                    f"{tc.get('name')} has failed repeatedly. Prevent token waste by stopping this loop.",
                    iteration=iteration,
                )
                runaway_guard_reason = (
                    "Tool loop stability issue. Stopping to prevent repeated tool-loop failure waste."
                )
                state.error = "Tool loop repeated failures"
                state.finished = True
                break

        if state.finished or state.user_interrupted:
            break

    if not state.finished and not state.user_interrupted:
        # NOT YET FIXED — deliberately left as an error, and here is why.
        #
        # Recording "I used up my own allowance" as a failed run is wrong: the work
        # survives on disk and every instrument that reads these records learns
        # something false. The fix is a THIRD state — done / paused-and-continuable /
        # failed — because the two that exist collapse "unfinished" into "failed".
        #
        # I tried the one-line version (drop state.error, emit STATUS) and it made
        # things worse: with no error set, post-loop completion emits AGENT_DONE, so
        # a run that stopped mid-repair would claim it had finished. Claiming
        # completion you did not reach is a worse lie than claiming a failure you did
        # not have. test_optimal_effort_exhaustion_is_incomplete_not_done exists to
        # catch exactly that and correctly caught me.
        #
        # Doing this properly means teaching handle_post_loop_completion a paused
        # outcome that keeps the artifacts and suppresses the done event. That is a
        # real change, not a line edit, and it should be made deliberately.
        runaway_guard_reason = (
            f"Pass budget exhausted after {max_iter} passes while work was still active. "
            "The task is incomplete; continue it in the same conversation."
        )
        state.error = runaway_guard_reason
        state.finished = True
        yield AgentEvent.agent_error(runaway_guard_reason, iteration=max(0, max_iter - 1))

    # Delegate post-loop completion (validation, quality gates, final events) to helper
    completion_events = handle_post_loop_completion(
        self,
        state,
        routing_text,
        route,
        job_type,
        mode,
        tools_policy,
        applied_token_economy,
        max_iterations,
        _quality_retry_count,
        _quality_carry_forward_events,
        # Loop state metrics
        usage_before,
        stream_usage,
        iter_token_estimates,
        effective_mode,
        peak_context_tokens,
        memory_tokens,
        tool_chars_total,
        tool_chars_kept,
        effective_tools_policy,
        autonomy_name,
        route_input_source,
        followup_suppressed_count,
        thought_leak_suppressed_count,
        full_auto_reprompt_count,
        clarification_question_cap,
        clarification_questions_asked,
        clarification_reprompt_count,
        best_practice_gate_active,
        best_practice_gate_source,
        code_output_guard_reprompts,
        code_output_guard_last_issue,
        strict_issue_ownership,
        high_prompt_spend_fail_iters,
        token_economy_meta,
        runtime_skills_payload,
        provider_tpm_budget,
        provider_prompt_window,
        mode_context_budget,
        hard_context_budget,
        emergency_context_budget,
        iter_prompt_warn_cap,
        iter_prompt_hard_cap,
        iter_prompt_spends,
        cumulative_context_tokens,
        runaway_guard_reason,
        provider_tpm_limit,
        provider_prompt_tokens_last_minute,
        provider_tpm_wait_events,
        provider_tpm_wait_seconds,
        quality_tool_events,
        provider_prompt_tracker.prune,
    )
    async with aclosing(completion_events):
        async for completion_event in completion_events:
            yield completion_event
