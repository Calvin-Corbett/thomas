"""Main agent loop execution and event streaming."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.checkin_policy import resolve_checkin_policy
from thomas.agent.constraint_envelope import ConstraintEnvelope, envelope_events
from thomas.agent.hook_events import HookEvent, emit_hook
from thomas.agent.loop_completion import handle_post_loop_completion
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_helpers import (
    _coerce_async_iterator,
    _ensure_llm_hardened_client,
    _validate_benchmark_code_output,
    httpx_ConnectError,
)
from thomas.agent.loop_tool_protocol import (
    _MAX_TOOL_RESULT_CHARS as _MAX_TOOL_RESULT_CHARS,
)
from thomas.agent.loop_tool_protocol import (
    _canonical_code_tool_name as _canonical_code_tool_name,
)
from thomas.agent.loop_tool_protocol import (
    _code_tool_action as _code_tool_action,
)
from thomas.agent.loop_tool_protocol import (
    _failed_tool_signature as _failed_tool_signature,
)
from thomas.agent.loop_tool_protocol import (
    _is_code_mutation_name as _is_code_mutation_name,
)
from thomas.agent.loop_tool_protocol import (
    _record_failed_tool as _record_failed_tool,
)
from thomas.agent.loop_tool_protocol import (
    _shell_command_is_mutation as _shell_command_is_mutation,
)
from thomas.agent.loop_tool_protocol import (
    _tool_result_with_recovery as _tool_result_with_recovery,
)
from thomas.agent.loop_tool_protocol import (
    _tool_spec_name as _tool_spec_name,
)
from thomas.agent.response_tone import (
    best_practice_default_hint,
    simplified_review_default_hint,
)
from thomas.agent.routing import PATH_CODING, PATH_MODEL_OWNED
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
from thomas.core.autonomy import autonomy_spec
from thomas.core.config import load_config
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMError
from thomas.core.llm_shared import callable_accepts_keyword
from thomas.core.rules_of_road import build_remediation_prompt, evaluate_rules
from thomas.core.token_economy import (
    build_token_economy_meta,
    coerce_base_iterations,
    compute_max_passes,
    loop_context_budgets,
    loop_iteration_prompt_caps,
    normalize_token_economy_level,
    runtime_overhead_policy,
)
from thomas.core.tokens import estimate_tokens

if TYPE_CHECKING:
    from thomas.agent.loop import AgentLoop

log = logging.getLogger(__name__)

_TPM_WINDOW_SECONDS = 60.0
_TPM_WAIT_SLICE_SECONDS = 20.0


def _connection_error_message(llm: Any) -> str:
    """Name the provider that actually dropped the connection.

    The old template printed ``Cannot connect to LLM at {base_url}. Is Ollama
    running?`` for every provider — but hosted profiles (ChatGPT/Codex) have
    no base_url, so a network blip mid-run surfaced as ``at .`` with advice
    to start Ollama: a diagnosis that was wrong in every part. The Ollama
    hint belongs only to a local endpoint."""
    cfg = getattr(llm, "config", None)
    base_url = str(getattr(cfg, "base_url", "") or "").strip()
    provider = str(getattr(cfg, "provider", "") or "").strip()
    model = str(getattr(cfg, "model", "") or "").strip()
    target = base_url or provider or model or "the configured model provider"
    message = f"Lost the connection to {target} mid-run (network drop or expired login)."
    if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
        message += " If this is a local Ollama endpoint, check: ollama serve"
    return message


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
    # ``prompt`` is the complete model context. ``intent_text`` remains the
    # user-visible current turn for receipts, but no deterministic layer
    # classifies either string before the model sees them.
    prompt_text = prompt if isinstance(prompt, str) else ""
    if isinstance(prompt, list):
        for part in prompt:
            if isinstance(part, dict) and part.get("type") == "text":
                prompt_text += str(part.get("text", "")) + "\n"
        prompt_text = prompt_text.strip()
    request_text = str(intent_text) if intent_text is not None else prompt_text
    routing_text = request_text
    benchmark_mode = str(job_type or "").strip().lower() == "benchmark"
    current_job_type = str(job_type or "").strip().lower()
    raw_write_guard_limit = str(os.environ.get("THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT") or "6").strip()
    try:
        write_guard_limit = int(raw_write_guard_limit)
    except (TypeError, ValueError, OverflowError):
        write_guard_limit = 6
    self._current_job_type = current_job_type
    self._self_development_write_guard = (
        {
            "inspection_count": 0,
            "write_seen": False,
            "limit": max(0, min(write_guard_limit, 50)),
        }
        if current_job_type == "self_development"
        else None
    )

    # Provider policy and structured tool authorization remain active. Thomas
    # does not inspect prompt words to pre-reject a natural-language turn.
    route_input = routing_text
    route_input_source = "current_turn"
    route = self._router.decide(
        routing_text,
        requested_mode=mode,
        requested_tools_policy=tools_policy,
    )
    prompt_route_path = (
        PATH_CODING
        if current_job_type in {"benchmark", "coding", "coding_task", "self_development"}
        else PATH_MODEL_OWNED
    )
    autonomy = autonomy_spec(self._autonomy_level)
    autonomy_name = str(autonomy.name)
    effective_mode = route.mode
    applied_token_economy = normalize_token_economy_level(token_economy)
    token_economy_meta = build_token_economy_meta(token_economy, applied_token_economy)
    overhead_policy = runtime_overhead_policy(applied_token_economy)
    self._memory_include_profile_economy_cap = bool(overhead_policy.include_memory_profile)
    _budget_economy = applied_token_economy
    strict_issue_ownership = bool(
        self._non_coder_profile
        or str(self._profile_type or "").strip().lower() == "non_coder"
        or str(self._profile_type or "").strip().lower() == "non-coder"
    )
    best_practice_gate_active = bool(overhead_policy.include_best_practice_hint) and bool(self._non_coder_profile)
    best_practice_gate_source = "profile_non_coder" if bool(self._non_coder_profile) else ""

    review_quality_hint = ""
    if overhead_policy.include_review_quality_hint:
        review_quality_hint = simplified_review_default_hint(
            self._review_depth,
            non_coder_profile=bool(self._non_coder_profile),
        )
    best_practice_hint = ""
    if overhead_policy.include_best_practice_hint and bool(self._non_coder_profile):
        best_practice_hint = best_practice_default_hint()
    code_output_validation_enabled = benchmark_mode
    runtime_skills_context = ""
    runtime_skills_payload: dict[str, Any] = {
        "enabled": False,
        "discovered_count": 0,
        "selected_count": 0,
        "explicit_mentions": [],
        "pinned_matches": [],
        "roots": [],
        "selected": [],
    }
    # Runtime skill policy owns explicit/pinned skill handling.  AgentLoop does
    # not inspect prompt words to decide whether discovery should run.
    skills_mode = str(overhead_policy.runtime_skills_mode or "off").strip().lower()
    should_resolve_runtime_skills = skills_mode in {"auto", "explicit"}
    if should_resolve_runtime_skills:
        try:
            runtime_skills = resolve_runtime_skills(
                self.config,
                prompt_text=routing_text,
                relevance_text=route_input,
                route_path=prompt_route_path,
                cwd=Path.cwd(),
            )
            runtime_skills_context = format_runtime_skills_context(runtime_skills)
            runtime_skills_payload = runtime_skills.to_event_payload()
        except Exception as e:  # REVIEWED: log-and-continue — skill discovery optional, graceful fallback
            log.warning("Runtime skills resolution failed: %s", e)
            runtime_skills_payload["error"] = f"{type(e).__name__}: {e}"
    usage_before = self._session_usage_snapshot()
    stream_usage = self._normalize_usage(0, 0, 0)

    # Effort controls a bounded number of passes. Explicit callers can still
    # provide an exact pass count; model context fit is enforced per request.
    configured_max_iter = coerce_base_iterations(getattr(self.config, "max_agent_iterations", None))
    if max_iterations is not None:
        max_iter = coerce_base_iterations(max_iterations)
    else:
        max_iter = compute_max_passes(applied_token_economy, configured_max_iter)
    # The model owns whether to answer, clarify, or call a capability.  These
    # counters remain in receipts for compatibility but no prose classifier
    # triggers hidden clarification rewrites.
    clarification_question_cap = 0
    full_auto_reprompt_count = 0
    clarification_questions_asked = 0
    clarification_reprompt_count = 0
    effective_tools_policy = route.tools_policy
    forced_tools_policy = autonomy.force_tools_policy
    if forced_tools_policy == "never":
        # Chat autonomy is a permission boundary, not an intent guess.
        effective_tools_policy = "never"
    elif tools_policy == "auto" and forced_tools_policy in {"auto", "always"}:
        effective_tools_policy = str(forced_tools_policy)

    tool_specs = self._select_tools(routing_text, policy=effective_tools_policy, route=route)

    preserve_first, preserve_last = self._history_preserve_counts(route)
    history_token_cap = self._history_token_cap(route)
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
    memory_text = ""
    continuity_hint = ""
    test_visibility_hint = ""
    library_text = ""
    memory_tokens = 0
    mode_context_budget, hard_context_budget, emergency_context_budget = loop_context_budgets(
        _budget_economy,
        effective_mode,
    )
    iter_prompt_warn_cap, iter_prompt_hard_cap = loop_iteration_prompt_caps(
        _budget_economy,
        effective_mode,
    )
    try:
        provider_tpm_limit = int(self._provider_tpm_limit() or 0)
    except (TypeError, ValueError):
        provider_tpm_limit = 0
    provider_tpm_budget = 0
    if provider_tpm_limit > 0:
        try:
            provider_tpm_headroom = float(self._provider_tpm_headroom() or 0.90)
        except (TypeError, ValueError):
            provider_tpm_headroom = 0.90
        provider_tpm_headroom = max(0.5, min(provider_tpm_headroom, 1.0))
        provider_tpm_budget = max(1, int(provider_tpm_limit * provider_tpm_headroom))
    provider_prompt_window: list[tuple[float, int]] = []
    provider_tpm_wait_events = 0
    provider_tpm_wait_seconds = 0.0
    provider_prompt_tokens_last_minute = 0
    stream_prompt_prev = 0

    def _prune_prompt_window(now_ts: float) -> None:
        cutoff = now_ts - _TPM_WINDOW_SECONDS
        if not provider_prompt_window:
            return
        provider_prompt_window[:] = [(ts, tok) for (ts, tok) in provider_prompt_window if ts >= cutoff]

    def _projected_wait_seconds(next_prompt_tokens: int) -> tuple[float, int, int]:
        if provider_tpm_budget <= 0:
            return 0.0, 0, 0
        now_ts = time.monotonic()
        _prune_prompt_window(now_ts)
        current_prompt = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
        projected_prompt = current_prompt + max(0, int(next_prompt_tokens))
        if projected_prompt <= provider_tpm_budget:
            return 0.0, projected_prompt, current_prompt

        running_prompt = current_prompt
        wait_s = _TPM_WINDOW_SECONDS
        for ts, tok in provider_prompt_window:
            running_prompt -= max(0, int(tok))
            if running_prompt + max(0, int(next_prompt_tokens)) <= provider_tpm_budget:
                wait_s = max(0.25, _TPM_WINDOW_SECONDS - (now_ts - ts))
                break
        return wait_s, projected_prompt, current_prompt

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

    if not benchmark_mode:
        self._apply_memory_policy(route)

    # Record user message in memory
    if request_text and not benchmark_mode:
        self._record_event("user_message", request_text)
    if routing_text:
        if not benchmark_mode:
            memory_mode = self.config.memory.mode or "auto"
            if effective_mode == "fast":
                memory_mode = "fast"
            if effective_mode == "thinking":
                memory_mode = "thorough"
            memory_text = self._retrieve_memory(
                routing_text,
                mode=memory_mode,
                budget_override=route.memory_budget_tokens,
            )
    test_visibility_hint = ""
    library_text = ""
    if best_practice_gate_active and best_practice_hint and not memory_text:
        memory_text = str(best_practice_hint)
    elif best_practice_gate_active and best_practice_hint and best_practice_hint not in memory_text:
        memory_text = memory_text + "\n\n" + str(best_practice_hint)
    if overhead_policy.include_library_context and not benchmark_mode:
        library_text = self._retrieve_library(routing_text, route)
        extra_context_parts: list[str] = []
        if memory_text:
            extra_context_parts.append(str(memory_text))
        if continuity_hint:
            extra_context_parts.append(str(continuity_hint))
        if best_practice_gate_active and best_practice_hint and best_practice_hint not in memory_text:
            extra_context_parts.append(str(best_practice_hint))
        if code_output_validation_enabled:
            extra_context_parts.append("Return ONLY the requested output format for this task, no prose or commentary.")
        if review_quality_hint:
            extra_context_parts.append(str(review_quality_hint))
        if test_visibility_hint:
            extra_context_parts.append(str(test_visibility_hint))
        if library_text:
            extra_context_parts.append(str(library_text))
        memory_text = "\n\n".join([p for p in extra_context_parts if p is not None and str(p).strip()])

        memory_tokens = estimate_tokens(memory_text)

    # Add user message to conversation for history
    self._conversation.append({"role": "user", "content": prompt})
    turn_user_content: Any = prompt

    # Mid-run check-in policy (CAP-051): zero overhead unless configured.
    checkin_policy = getattr(self, "_checkin_policy", None) or resolve_checkin_policy(self.config)
    if checkin_policy is not None:
        self._checkin_policy = checkin_policy

    # Constraint envelope (CAP-048): token ceiling + checkpoint summaries with
    # deterministic stop reasons. Inert unless configured via env, so default
    # behavior is unchanged.
    constraint_envelope = ConstraintEnvelope.from_env()

    for iteration in range(max_iter):
        state.iteration = iteration

        # Auto-compact conversation if approaching token budget.
        # This runs before _build_messages to avoid hard truncation.
        if iteration >= 1:
            try:
                compact_result = await self._auto_compact_if_needed(
                    hard_cap=self._context_window,
                    threshold=0.70,
                    preserve_recent=max(6, preserve_last + 2),
                )
                if compact_result:
                    log.info(
                        "Auto-compacted conversation: %d -> %d tokens (saved %d)",
                        compact_result["original_tokens"],
                        compact_result["compacted_tokens"],
                        compact_result["tokens_saved"],
                    )
            except Exception as _ac_err:
                log.debug("Auto-compaction check failed (non-fatal): %s", _ac_err)

        # Build messages with context window management
        # Only inject memory on first iteration
        mem = ""
        if iteration == 0:
            mem = memory_text
            if continuity_hint:
                mem = (mem + "\n\n" + continuity_hint).strip() if mem else continuity_hint
            if test_visibility_hint:
                mem = (mem + "\n\n" + test_visibility_hint).strip() if mem else test_visibility_hint
            if library_text:
                mem = (mem + "\n\n" + library_text).strip() if mem else library_text
        self_development_job = current_job_type == "self_development"
        # The model keeps every tool for the whole run. Thomas used to strip the
        # read tools after 6 inspections, and ALL tools after 6 post-edit reads, so
        # the one action most likely to catch a mistake -- re-reading what you just
        # wrote -- was removed precisely when it mattered.
        iteration_tool_specs = tool_specs
        messages = self._build_messages(
            state,
            memory_text=mem,
            tool_specs=iteration_tool_specs,
            include_purpose=bool(route.include_purpose) and bool(overhead_policy.include_purpose_brief),
            preserve_first=preserve_first,
            preserve_last=preserve_last,
            history_token_cap=history_token_cap,
            route_path=prompt_route_path,
            skills_context=runtime_skills_context,
            include_autonomy_profile=bool(overhead_policy.include_autonomy_profile),
            include_editing_policy=bool(overhead_policy.include_editing_policy) and not self_development_job,
            include_project_instructions=bool(overhead_policy.include_project_instructions),
        )
        iter_token_estimates.append(int(state.token_estimate))
        cumulative_context_tokens += int(state.token_estimate)
        peak_context_tokens = max(peak_context_tokens, int(state.token_estimate))

        if provider_tpm_budget > 0:
            while True:
                next_prompt_estimate = int(state.token_estimate)
                if provider_prompt_window:
                    observed_avg = int(
                        sum(max(0, int(tok)) for _, tok in provider_prompt_window) / max(1, len(provider_prompt_window))
                    )
                    next_prompt_estimate = max(next_prompt_estimate, observed_avg)
                wait_s, projected_prompt, current_prompt = _projected_wait_seconds(next_prompt_estimate)
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
                    yield AgentEvent.tool_call_end(tc_data["id"], iteration=iteration)

                elif event.type == "error":
                    # Some providers surface errors as stream events.
                    err = str(event.data.get("error", "")).strip() or "LLM error"
                    llm_stream_error = err
                    yield AgentEvent.agent_error(err, iteration=iteration)

                elif event.type == "done":
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
            if int(getattr(e, "status", 0) or 0) == 429 and iteration + 1 < max_iter:
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
            yield AgentEvent.agent_error(error_msg, iteration=iteration)
            state.error = error_msg
            state.finished = True
            break

        except (httpx_ConnectError, ConnectionError, OSError):
            error_msg = _connection_error_message(self.llm)
            yield AgentEvent.agent_error(error_msg, iteration=iteration)
            state.error = error_msg
            state.finished = True
            break

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
                provider_prompt_window.append((time.monotonic(), int(stream_prompt_delta)))
                stream_prompt_prev = stream_prompt_now
                _prune_prompt_window(time.monotonic())
                provider_prompt_tokens_last_minute = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
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
                self._conversation.append({"role": "user", "content": user_prompt})
                continue
            issue_error = f"Code-output guard blocked completion: {code_output_guard_last_issue}".strip()
            state.error = issue_error
            yield AgentEvent.agent_error(issue_error, iteration=iteration)
            state.finished = True
            break

        state.aggregate_response += iter_text

        # If no tool calls, we're done
        if not pending_tool_calls:
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
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if iter_text:
            assistant_msg["content"] = iter_text
        else:
            assistant_msg["content"] = ""
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
            if not tc:
                tc = {"id": tc_id, "name": result_event.data.get("tool_name", "tool"), "arguments": "{}"}

            parsed_args, _parse_err = self._parse_tool_args(tc.get("arguments"))

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
            if len(result_text) > _MAX_TOOL_RESULT_CHARS:
                footer = (
                    f"\n\n... (truncated, {len(result_text):,} chars total. Use start_line/end_line for large files.)"
                )
                result_text = result_text[: _MAX_TOOL_RESULT_CHARS - len(footer)] + footer
            tool_chars_total += original_len
            tool_chars_kept += len(result_text)

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            }
            self._conversation.append(tool_msg)

            # ── message interruption check ──
            # Between tool completions, check if the user sent a new message.
            # This allows graceful cancellation mid-loop for responsive interaction.
            if self._message_queue is not None:
                try:
                    user_interrupt = self._message_queue.get_nowait()
                    if user_interrupt is None or str(user_interrupt).strip().lower() == "stop":
                        state.user_interrupted = True
                        state.finished = True
                        yield AgentEvent(
                            type=EventType.AGENT_END,
                            data={"reason": "user_interrupted", "message": "Run cancelled by user."},
                            iteration=iteration,
                        )
                        break
                    interrupt_text = str(user_interrupt).strip()
                    if interrupt_text:
                        # Inject live follow-up user input into the active run.
                        # The next iteration will route against this updated request.
                        self._conversation.append({"role": "user", "content": interrupt_text})
                        turn_user_content = interrupt_text
                        yield AgentEvent(
                            type=EventType.THINKING,
                            data={"text": "Received additional user instructions. Adapting plan.\n"},
                            iteration=iteration,
                        )
                except Exception:
                    # Handles both asyncio.QueueEmpty and queue.Empty
                    pass

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

            if current_job_type == "coding":
                tool_action = _code_tool_action(str(tc.get("name") or ""), args_meta)
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
    async for completion_event in handle_post_loop_completion(
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
        _prune_prompt_window,
    ):
        yield completion_event
