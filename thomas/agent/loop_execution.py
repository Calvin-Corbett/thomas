"""Main agent loop execution and event streaming."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.response_tone import (
    best_practice_default_hint,
    best_practice_gate_hint,
    live_test_default_hint,
    prompt_requests_code_output,
    simplified_review_default_hint,
)
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
from thomas.core.autonomy import autonomy_spec
from thomas.core.config import load_config
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMError
from thomas.core.rules_of_road import build_remediation_prompt, evaluate_rules
from thomas.core.token_economy import (
    build_token_economy_meta,
    loop_context_budgets,
    loop_iteration_prompt_caps,
    loop_tool_spec_budgets,
    normalize_token_economy_level,
    runtime_overhead_policy,
)
from thomas.core.tokens import estimate_tokens, estimate_tools_tokens

try:
    from thomas.agent.context_compaction import compact_conversation

    _HAS_COMPACTION = True
except ImportError:
    _HAS_COMPACTION = False

from thomas.agent.loop_completion import handle_post_loop_completion
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_helpers import (
    _coerce_async_iterator,
    _ensure_llm_hardened_client,
    _validate_benchmark_code_output,
    httpx_ConnectError,
)

if TYPE_CHECKING:
    from thomas.agent.loop import AgentLoop

log = logging.getLogger(__name__)

_MAX_TOOL_RESULT_CHARS = 5_000
_TPM_WINDOW_SECONDS = 60.0
_TPM_MAX_AUTO_WAIT_S = 20.0
_REPLY_FIRST_ROUTE_PATHS = frozenset({"casual_chat", "personal_context", "assistant_meta", "general", "planning"})
_STREAM_HOLDBACK_CHARS = 32


def _is_reply_first_route(*, route_path: str, project_related: bool, explicit_action: bool) -> bool:
    path = str(route_path or "").strip().lower()
    if path == "planning":
        return True
    if path not in _REPLY_FIRST_ROUTE_PATHS:
        return False
    return not (project_related and explicit_action)


def _stable_text_emit_length(text: str) -> int:
    src = str(text or "")
    if not src:
        return 0
    if src.endswith(("\n", ".", "!", "?", ":")):
        return len(src)
    if len(src) <= _STREAM_HOLDBACK_CHARS:
        return 0
    return len(src) - _STREAM_HOLDBACK_CHARS


async def _agent_loop_run(
    self: AgentLoop,
    prompt: Any,
    *,
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
    # Extract plain text for heuristics/memory even if prompt is multimodal.
    prompt_text = prompt if isinstance(prompt, str) else ""
    if isinstance(prompt, list):
        for part in prompt:
            if isinstance(part, dict) and part.get("type") == "text":
                prompt_text += str(part.get("text", "")) + "\n"
        prompt_text = prompt_text.strip()
    benchmark_mode = str(job_type or "").strip().lower() == "benchmark"

    # Suspicious prompt gate: if the prompt matches jailbreak/extraction patterns,
    # require Windows PIN before continuing. Abort if denied.
    try:
        from thomas.tools.windows_auth import check_prompt_suspicious, gate_suspicious_prompt

        is_suspicious, matched_pattern = check_prompt_suspicious(prompt_text)
        if is_suspicious:
            log.warning("Suspicious prompt detected (matched: %r). Requiring PIN.", matched_pattern)
            yield AgentEvent(
                type=EventType.SECURITY_FLAG,
                data={
                    "flag": "suspicious_prompt",
                    "matched_pattern": matched_pattern[:100],
                    "message": "This request matched a suspicious pattern. Windows PIN required to proceed.",
                },
            )
            # Pass precomputed result — avoids running the regex a second time
            authorized = gate_suspicious_prompt(
                prompt_text,
                action_description="Proceed with flagged request",
                precomputed=(is_suspicious, matched_pattern),
                no_human_mode=os.environ.get("THOMAS_NO_HUMAN_MODE")
                or os.environ.get("THOMAS_GUARDRAILS_NO_HUMAN_MODE")
                or "human",
            )
            if not authorized:
                yield AgentEvent(
                    type=EventType.AGENT_END,
                    data={
                        "reason": "suspicious_prompt_denied",
                        "message": "Request blocked: Windows PIN not entered or incorrect.",
                    },
                )
                return
            log.info("Suspicious prompt authorized via Windows PIN.")
    except Exception as e:  # REVIEWED: log-and-continue — gate check is optional, non-fatal
        log.debug("Suspicious prompt gate check failed (non-fatal): %s", e)

    route_input, route_input_source = self._routing_input_text(prompt_text)

    # Check conversation intelligence for multi-turn context
    is_followup = self.check_if_followup(prompt_text)
    user_is_confused = self.detect_user_confusion(prompt_text)
    if is_followup:
        # For follow-ups, try to resolve pronouns and references
        resolved_prompt = self.resolve_message_references(prompt_text)
        # Only use resolved version if it added context
        if len(resolved_prompt) > len(prompt_text):
            prompt_text = resolved_prompt

    route = self._router.decide(
        route_input,
        requested_mode=mode,
        requested_tools_policy=tools_policy,
        is_followup=is_followup,
    )
    route_path = str(route.path or "")
    project_related = self._is_project_related_prompt(prompt_text)
    explicit_action = self._has_explicit_action_intent(prompt_text)
    continuation_turn = bool(route_input_source == "history_augmented")
    reply_first_route = _is_reply_first_route(
        route_path=route_path,
        project_related=project_related,
        explicit_action=explicit_action,
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
    best_practice_gate_active = bool(overhead_policy.include_best_practice_hint) and (
        bool(self._non_coder_profile) or bool(best_practice_gate_hint(prompt_text))
    )
    best_practice_gate_source = "profile_non_coder" if bool(self._non_coder_profile) else ""
    if not best_practice_gate_source and best_practice_gate_hint(prompt_text):
        best_practice_gate_source = "prompt"

    review_quality_hint = ""
    if overhead_policy.include_review_quality_hint:
        review_quality_hint = simplified_review_default_hint(
            self._review_depth,
            non_coder_profile=bool(self._non_coder_profile),
        )
    best_practice_hint = ""
    if overhead_policy.include_best_practice_hint:
        best_practice_hint = (
            best_practice_default_hint() if bool(self._non_coder_profile) else best_practice_gate_hint(prompt_text)
        )
    code_output_validation_enabled = bool(prompt_requests_code_output(prompt_text))
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
    # Skip runtime skill discovery on reply-first turns unless the user
    # explicitly asks for a skill.
    prompt_lower = str(prompt_text or "").lower()
    explicit_skill_hint = ("$" in str(prompt_text or "")) or ("skill " in prompt_lower)
    skills_mode = str(overhead_policy.runtime_skills_mode or "off").strip().lower()
    should_resolve_runtime_skills = False
    if skills_mode == "auto":
        should_resolve_runtime_skills = (not reply_first_route) or explicit_skill_hint
    elif skills_mode == "explicit":
        should_resolve_runtime_skills = explicit_skill_hint
    if should_resolve_runtime_skills:
        try:
            runtime_skills = resolve_runtime_skills(
                self.config,
                prompt_text=prompt_text,
                relevance_text=route_input,
                route_path=str(route.path or ""),
                cwd=Path.cwd(),
            )
            runtime_skills_context = format_runtime_skills_context(runtime_skills)
            runtime_skills_payload = runtime_skills.to_event_payload()
        except Exception as e:  # REVIEWED: log-and-continue — skill discovery optional, graceful fallback
            log.warning("Runtime skills resolution failed: %s", e)
            runtime_skills_payload["error"] = f"{type(e).__name__}: {e}"
    usage_before = self._session_usage_snapshot()
    stream_usage = self._normalize_usage(0, 0, 0)

    if self._is_tool_usage_question(prompt_text):
        preserve_first, preserve_last = self._history_preserve_counts(route)
        history_token_cap = self._history_token_cap(route)
        answer = self._tool_usage_response()

        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "prompt": prompt_text,
                "route": route.to_dict(),
                "route_input_source": route_input_source,
                "mode": effective_mode,
                "tools_policy": "never",
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

        if prompt_text and not benchmark_mode:
            self._record_event("user_message", prompt_text)
            self._capture_profile_hints(prompt_text)
        self._conversation.append({"role": "user", "content": prompt})
        self._sync_user_message_to_intelligence(prompt)
        self._conversation.append({"role": "assistant", "content": answer})
        self._sync_assistant_message_to_intelligence(answer)
        yield AgentEvent.text_delta(answer, iteration=0)

        usage_obj = {
            "prompt_tokens": estimate_tokens(prompt_text),
            "completion_tokens": estimate_tokens(answer),
            "total_tokens": estimate_tokens(prompt_text) + estimate_tokens(answer),
        }
        token_report = self._build_token_report(
            prompt_text=prompt_text,
            usage_obj=usage_obj,
            mode=effective_mode,
            iterations=1,
            peak_context_tokens=usage_obj["total_tokens"],
            avg_context_tokens=usage_obj["total_tokens"],
            memory_tokens=0,
            tool_chars_total=0,
            tool_chars_kept=0,
        )
        token_report["route"] = route.to_dict()
        token_report["effective_tools_policy"] = "never"
        token_report["autonomy_level"] = int(self._autonomy_level)
        token_report["autonomy_name"] = autonomy_name
        token_report["continuity"] = {
            "route_input_source": route_input_source,
            "followup_suppressed_count": 0,
            "thought_leak_suppressed_count": 0,
            "full_auto_reprompt_count": 0,
            "clarification_question_cap": 0,
            "clarification_questions_asked": 0,
            "clarification_reprompt_count": 0,
            "best_practice_gate_active": bool(best_practice_gate_active),
            "best_practice_gate_source": str(best_practice_gate_source),
            "profile_type": str(self._profile_type),
            "code_output_guard_reprompts": 0,
            "code_output_guard_last_issue": "",
            "strict_issue_ownership": bool(strict_issue_ownership),
            "high_prompt_spend_fail_iters": 0,
        }
        token_report["token_economy"] = dict(token_economy_meta)
        token_report["skills"] = dict(runtime_skills_payload)
        cfg_errors: list[str] = []
        cfg_unknown: list[str] = []
        try:
            cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
            loaded_cfg = load_config(cfg_path)
            cfg_errors = loaded_cfg.validate()
            cfg_unknown = list(loaded_cfg.unknown_core_keys)
        except Exception as e:  # REVIEWED: log-and-continue — audit optional, sets error list
            cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

        quality_cfg = getattr(self.config, "quality", None)
        combined_quality_events = list(_quality_carry_forward_events or [])
        rules_report = evaluate_rules(
            route_path=str(route.path or ""),
            prompt_text=prompt_text,
            response_text=answer,
            tool_events=combined_quality_events,
            requested_job_type=job_type,
            config_errors=cfg_errors,
            unknown_core_keys=cfg_unknown,
            require_verification_for_coding=bool(getattr(quality_cfg, "require_verification_for_coding", True)),
            require_tests_for_code_edits=bool(getattr(quality_cfg, "require_tests_for_code_edits", False)),
            require_monolith_guard_for_coding=bool(getattr(quality_cfg, "require_monolith_guard_for_coding", True)),
            strict_issue_ownership=bool(strict_issue_ownership),
            skill_required_checks=list(runtime_skills_payload.get("required_checks") or []),
            attempt=int(_quality_retry_count),
            repo_root=Path.cwd(),
        )
        token_report["rules_of_road"] = rules_report

        quality_enabled = bool(getattr(quality_cfg, "enabled", True))
        quality_enforce = bool(getattr(quality_cfg, "enforce", True))
        quality_max_retries = max(
            0,
            min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)),
        )
        if strict_issue_ownership:
            quality_max_retries = max(quality_max_retries, 2)
        issue_ownership_signals = rules_report.get("signals") if isinstance(rules_report, dict) else {}
        if not isinstance(issue_ownership_signals, dict):
            issue_ownership_signals = {}
        issue_ownership_blocked = bool(
            bool(issue_ownership_signals.get("strict_issue_ownership"))
            and bool(issue_ownership_signals.get("unresolved_issue_detected"))
        )
        quality_required = not bool(rules_report.get("passed", False))
        if (
            quality_required
            and _quality_retry_count < quality_max_retries
            and ((quality_enabled and quality_enforce) or strict_issue_ownership)
        ):
            remediation_prompt = build_remediation_prompt(rules_report)
            if remediation_prompt:
                retry_job_type = str(job_type or rules_report.get("job_type") or "").strip().lower() or None
                async for retry_event in self.run(
                    remediation_prompt,
                    mode=mode,
                    tools_policy=tools_policy,
                    token_economy=applied_token_economy,
                    max_iterations=max_iterations,
                    job_type=retry_job_type,
                    _quality_retry_count=_quality_retry_count + 1,
                    _quality_carry_forward_events=combined_quality_events,
                ):
                    yield retry_event
                return
            if strict_issue_ownership and issue_ownership_blocked:
                block_error = (
                    "Issue-ownership quality gate blocked completion: "
                    "user-facing text still appears to describe unresolved issues or workaround-only work."
                )
                yield AgentEvent.agent_error(block_error, iteration=0)
            return
        if (
            quality_required
            and strict_issue_ownership
            and issue_ownership_blocked
            and _quality_retry_count >= quality_max_retries
        ):
            block_error = (
                "Issue-ownership quality gate blocked completion: "
                "user-facing text still appears to describe unresolved issues or workaround-only work."
            )
            yield AgentEvent.agent_error(block_error, iteration=0)
            return

        yield AgentEvent.agent_done(
            text=answer,
            iterations=1,
            tool_calls=0,
            usage=usage_obj,
            token_report=token_report,
        )
        return

    # Mode presets (the caller can still override with max_iterations).
    if max_iterations is not None:
        max_iter = max_iterations
    elif effective_mode == "fast":
        # Fast mode should not truncate task completion. Keep the same loop
        # budget as normal mode; "fast" is handled by lighter behavior/budgets.
        max_iter = self.config.max_agent_iterations
    elif effective_mode == "thinking":
        max_iter = min(self.config.max_agent_iterations * 2, 25)
    else:
        max_iter = self.config.max_agent_iterations
    if max_iterations is None and autonomy.prefers_extended_iterations:
        if effective_mode == "fast":
            # Fast mode still needs enough room for at least one tool turn + follow-up,
            # but should not inherit very long full-auto iteration budgets.
            max_iter = max(max_iter, min(max(self.config.max_agent_iterations, 2), 6))
        else:
            max_iter = max(max_iter, min(self.config.max_agent_iterations * 3, 32))
    action_route = route_path in ("coding_task", "debug_audit", "planning", "research")
    full_auto_action_turn = bool(
        int(self._autonomy_level) == 4 and (project_related or explicit_action or action_route)
    )
    clarification_budget_active = bool(project_related or explicit_action or action_route)
    clarification_question_cap = 2
    if clarification_budget_active:
        clarification_question_cap = 1
    if clarification_budget_active and explicit_action and int(self._autonomy_level) >= 3:
        clarification_question_cap = 0
    if continuation_turn:
        clarification_question_cap = 0 if clarification_budget_active else 1
    if full_auto_action_turn:
        clarification_question_cap = 0
    clarification_question_cap = max(0, int(clarification_question_cap))
    full_auto_reprompt_count = 0
    clarification_questions_asked = 0
    clarification_reprompt_count = 0
    effective_tools_policy = route.tools_policy
    if tools_policy == "auto" and route.tools_policy == "auto":
        if effective_mode == "fast":
            effective_tools_policy = "never"
        elif effective_mode == "thinking":
            effective_tools_policy = "always"
    if tools_policy == "auto" and reply_first_route and not explicit_action and not project_related:
        effective_tools_policy = "never"

    # API/cloud providers should always have tools available unless the
    # user explicitly disabled them. The routing heuristic was originally
    # tuned for local models where hiding tools saves context.
    from thomas.models.protocol import profile_prefers_always_tools

    if (
        tools_policy == "auto"
        and effective_tools_policy == "never"
        and profile_prefers_always_tools(self.llm.config)
        and (project_related or explicit_action)
    ):
        effective_tools_policy = "auto"
    if tools_policy == "auto" and effective_tools_policy == "never" and project_related:
        effective_tools_policy = "auto"
    if self._autonomy_level == 2 and effective_tools_policy == "always":
        effective_tools_policy = "auto"
    if autonomy.force_tools_policy in ("never", "auto", "always"):
        forced = str(autonomy.force_tools_policy)
        if forced == "always" and reply_first_route and not explicit_action and not project_related:
            # Only downgrade "always" to "never" when truly conversational
            # (no action verbs AND no project signals).
            effective_tools_policy = "never"
        else:
            effective_tools_policy = forced

    tool_specs = self._select_tools(prompt_text, policy=effective_tools_policy, route=route)

    # EMERGENCY BRAKE: Tool definition bloat.
    if tool_specs:
        hard_tool_count_cap, max_tool_spec_tokens = loop_tool_spec_budgets(
            _budget_economy,
            effective_mode,
        )
        if len(tool_specs) > hard_tool_count_cap:
            tool_specs = tool_specs[:hard_tool_count_cap]

        while len(tool_specs) > 1 and estimate_tools_tokens(tool_specs) > max_tool_spec_tokens:
            tool_specs = tool_specs[:-1]

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
    consecutive_failed_tool_iters = 0
    repeated_failure_signature = ""
    repeated_failure_count = 0
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
    provider_tpm_limit = self._provider_tpm_limit()
    provider_tpm_budget = 0
    if provider_tpm_limit > 0:
        provider_tpm_budget = max(1, int(provider_tpm_limit * self._provider_tpm_headroom()))
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
            "prompt": prompt_text,
            "route": route.to_dict(),
            "route_input_source": route_input_source,
            "mode": effective_mode,
            "tools_policy": effective_tools_policy,
            "autonomy_level": int(self._autonomy_level),
            "autonomy_name": autonomy_name,
            "token_economy": token_economy_meta,
            "library_enabled": bool(self._library is not None),
            "skills": dict(runtime_skills_payload),
            "conversation_intelligence": {
                "is_followup": is_followup,
                "user_is_confused": user_is_confused,
                "turn_count": self._conv_intel.turn_count,
                "current_topic": self._conv_intel.current_topic,
            },
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
    if prompt_text and not benchmark_mode:
        self._record_event("user_message", prompt_text)
        self._capture_profile_hints(prompt_text)
    # Keep reply-first turns lean unless continuity or policy signals need extra context.
    if prompt_text:
        should_retrieve_memory = bool(
            (not benchmark_mode)
            and (
                not reply_first_route
                or continuation_turn
                or user_is_confused
                or best_practice_gate_active
                or code_output_validation_enabled
            )
        )
        if should_retrieve_memory:
            memory_mode = self.config.memory.mode or "auto"
            if effective_mode == "fast":
                memory_mode = "fast"
            if effective_mode == "thinking":
                memory_mode = "thorough"
            memory_text = self._retrieve_memory(
                prompt_text,
                mode=memory_mode,
                budget_override=route.memory_budget_tokens,
            )
        continuity_hint = self._input_continuity_hint(prompt_text) if (continuation_turn or user_is_confused) else ""
    test_visibility_hint = ""
    if overhead_policy.include_test_visibility_hint and not reply_first_route:
        test_visibility_hint = live_test_default_hint(prompt_text)
    library_text = ""
    # Ensure best-practice gate hint reaches the system prompt even when the
    # library-context block doesn't run (e.g. reply_first_route or coding-task
    # routes without thinking mode). Tests in test_agent_loop_conversation.py
    # assert the hint is present whenever non_coder_profile=True.
    if best_practice_gate_active and best_practice_hint and not memory_text:
        memory_text = str(best_practice_hint)
    elif best_practice_gate_active and best_practice_hint and best_practice_hint not in memory_text:
        memory_text = memory_text + "\n\n" + str(best_practice_hint)
    if (
        overhead_policy.include_library_context
        and not benchmark_mode
        and (not reply_first_route)
        and (route_path != "coding_task" or str(effective_mode or "").strip().lower() == "thinking")
    ):
        library_text = self._retrieve_library(prompt_text, route)
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
    self._sync_user_message_to_intelligence(prompt)

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
        messages = self._build_messages(
            state,
            memory_text=mem,
            tool_specs=tool_specs,
            include_purpose=bool(route.include_purpose) and bool(overhead_policy.include_purpose_brief),
            preserve_first=preserve_first,
            preserve_last=preserve_last,
            history_token_cap=history_token_cap,
            route_path=str(route.path or ""),
            skills_context=runtime_skills_context,
            include_autonomy_profile=bool(overhead_policy.include_autonomy_profile),
            include_editing_policy=bool(overhead_policy.include_editing_policy),
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
                if wait_s <= _TPM_MAX_AUTO_WAIT_S:
                    provider_tpm_wait_events += 1
                    provider_tpm_wait_seconds += float(wait_s)
                    yield AgentEvent.status(
                        (
                            f"Throttling {wait_s:.1f}s to avoid provider rate limit "
                            f"({projected_prompt:,}/{provider_tpm_budget:,} estimated prompt tokens/min)."
                        ),
                        iteration=iteration,
                    )
                    await asyncio.sleep(wait_s)
                    continue

                profile_name = str(getattr(self.llm.config, "name", "") or "active-model")
                runaway_guard_reason = (
                    "Stopped automatically to prevent provider rate-limit failure: "
                    f"projected prompt load {projected_prompt:,}/{provider_tpm_budget:,} "
                    f"tokens/min for profile '{profile_name}'. Retry in about {int(wait_s)}s."
                )
                yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                state.error = runaway_guard_reason
                state.finished = True
                break
            if state.finished:
                break

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
        # Reply-first routes can stream once a sanitized prefix is stable.
        # Execution-first routes still buffer the full answer for stronger hygiene.
        buffer_text_tokens = not reply_first_route
        streamed_visible_text = ""
        iter_prompt_start_total = int(stream_usage.get("prompt_tokens", 0) or 0)

        try:
            llm_stream_error: str | None = None
            await _ensure_llm_hardened_client(self.llm)
            llm_stream = await _coerce_async_iterator(
                self.llm.stream_chat(messages, tool_specs),
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
                    if not buffer_text_tokens:
                        visible_text, _ = self._sanitize_assistant_text(
                            "".join(text_chunks),
                            prompt_text=prompt_text,
                            route=route,
                            route_input_source=route_input_source,
                            pending_tool_calls=0,
                        )
                        flush_len = _stable_text_emit_length(visible_text)
                        visible_prefix = visible_text[:flush_len]
                        if visible_prefix.startswith(streamed_visible_text):
                            delta = visible_prefix[len(streamed_visible_text) :]
                            if delta:
                                streamed_visible_text = visible_prefix
                                yield AgentEvent.text_delta(delta, iteration=iteration)

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
                    # Codex app-server executes tools itself; treat tool_call_end as a tool result
                    # passthrough (do not execute via Thomas's tool registry).
                    if self.llm.config.provider == "codex" and "output" in event.data:
                        tc_id = str(event.data.get("id", ""))
                        tc_name = str(event.data.get("name", ""))
                        output = str(event.data.get("output", ""))
                        exit_code = event.data.get("exit_code")
                        tool_chars_total += len(output)
                        tool_chars_kept += len(output)

                        ok = True
                        if exit_code is not None:
                            try:
                                ok = int(exit_code) == 0
                            except (ValueError, TypeError):
                                ok = False

                        await self._audit_action(
                            kind="tool_action_result",
                            tool_call_id=tc_id,
                            tool_name=tc_name,
                            decision="EXECUTED" if ok else "FAILED",
                            payload={
                                "provider": "codex",
                                "ok": ok,
                                "exit_code": exit_code,
                                "output_preview": output[:1000],
                            },
                        )

                        yield AgentEvent.tool_call_end(tc_id, iteration=iteration)
                        yield AgentEvent(
                            type=EventType.TOOL_RESULT,
                            data={
                                "tool_id": tc_id,
                                "tool_name": tc_name,
                                "result": output[:4000],  # summary for event consumers
                                "result_text": output,  # full text (not fed back to LLM)
                                "ok": ok,
                                "duration_ms": 0,
                            },
                            iteration=iteration,
                        )
                        quality_command = ""
                        quality_path = ""
                        if not tc_name.lower().startswith("edit:"):
                            quality_command = tc_name
                        else:
                            quality_path = tc_name.split(":", 1)[1].strip()
                        if (not quality_path or quality_path == "?") and output.startswith("File changed:"):
                            quality_path = output.split(":", 1)[1].strip()
                        if quality_path == "?":
                            quality_path = ""
                        quality_tool_events.append(
                            {
                                "name": tc_name,
                                "ok": ok,
                                "command": quality_command,
                                "path": quality_path,
                                "output_preview": output[:2000],
                            }
                        )
                        state.total_tool_calls += 1
                        continue

                    tc_data = {
                        "id": event.data.get("id", ""),
                        "name": event.data.get("name", ""),
                        "arguments": event.data.get("arguments", ""),
                    }
                    pending_tool_calls.append(tc_data)
                    yield AgentEvent.tool_call_end(tc_data["id"], iteration=iteration)

                elif event.type == "error":
                    # Some providers (e.g. Codex bridge) surface errors as events.
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
            # Detect connection errors and give a helpful message
            if "connect" in error_msg.lower() or "refused" in error_msg.lower():
                base_url = self.llm.config.base_url
                error_msg = f"Cannot connect to LLM at {base_url}. Is Ollama running? Try: ollama serve"
            yield AgentEvent.agent_error(error_msg, iteration=iteration)
            state.error = error_msg
            state.finished = True
            break

        except (httpx_ConnectError, ConnectionError, OSError):
            base_url = self.llm.config.base_url
            error_msg = f"Cannot connect to LLM at {base_url}. Is Ollama running? Try: ollama serve"
            yield AgentEvent.agent_error(error_msg, iteration=iteration)
            state.error = error_msg
            state.finished = True
            break

        # Accumulate text response
        iter_text = "".join(text_chunks)
        iter_text, suppressed = self._sanitize_assistant_text(
            iter_text,
            prompt_text=prompt_text,
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

        # Clarification budget guardrail for action turns: avoid repeated
        # ask-back loops when the model can proceed with sensible defaults.
        is_clarifying_question = bool(not pending_tool_calls and self._looks_like_clarifying_question(iter_text))
        if is_clarifying_question:
            clarification_questions_asked += 1
        reached_clarification_cap = (
            clarification_questions_asked >= clarification_question_cap
            if full_auto_action_turn
            else clarification_questions_asked > clarification_question_cap
        )
        if (
            clarification_budget_active
            and is_clarifying_question
            and reached_clarification_cap
            and clarification_reprompt_count < 2
            and (iteration + 1) < max_iter
        ):
            clarification_reprompt_count += 1
            if full_auto_action_turn:
                full_auto_reprompt_count += 1
                nudge = self._full_auto_nudge(prompt_text, full_auto_reprompt_count)
            else:
                nudge = self._assume_and_proceed_nudge(
                    prompt_text,
                    retry_index=clarification_reprompt_count,
                    question_cap=clarification_question_cap,
                    questions_seen=clarification_questions_asked,
                    route_input_source=route_input_source,
                )
            self._conversation.append({"role": "user", "content": nudge})
            self._sync_user_message_to_intelligence(nudge)
            continue
        if buffer_text_tokens and iter_text:
            # Flush buffered text after full-auto guardrails accept it.
            yield AgentEvent.text_delta(iter_text, iteration=iteration)
        elif iter_text:
            if iter_text.startswith(streamed_visible_text):
                tail = iter_text[len(streamed_visible_text) :]
                if tail:
                    yield AgentEvent.text_delta(tail, iteration=iteration)
                    streamed_visible_text = iter_text
            elif not streamed_visible_text:
                yield AgentEvent.text_delta(iter_text, iteration=iteration)
                streamed_visible_text = iter_text

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

        if iter_prompt_hard_cap is not None and iter_prompt_spend > int(iter_prompt_hard_cap):
            high_prompt_spend_fail_iters += 1
            runaway_guard_reason = (
                "High prompt-token spend per iteration exceeded hard cap. "
                "Stopping to prevent token waste and runaway budget usage."
            )
            yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
            state.error = runaway_guard_reason
            state.finished = True
            break

        benchmark_validation_ok = True
        benchmark_issue = ""
        if str(job_type or "").strip().lower() == "benchmark" and code_output_validation_enabled:
            benchmark_validation_ok, benchmark_issue, _ = _validate_benchmark_code_output(
                prompt_text=prompt_text,
                continuation=iter_text,
            )
        if not benchmark_validation_ok:
            code_output_guard_reprompts += 1
            code_output_guard_last_issue = str(benchmark_issue or "")
            if (iteration + 1) < max_iter:
                guard_context = str(prompt_text or "").strip().replace("\n", " ")
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
                self._sync_user_message_to_intelligence(user_prompt)
                continue
            issue_error = f"Code-output guard blocked completion: {code_output_guard_last_issue}".strip()
            state.error = issue_error
            yield AgentEvent.agent_error(issue_error, iteration=iteration)
            state.finished = True
            break

        state.text_response += iter_text

        # If no tool calls, we're done
        if not pending_tool_calls:
            if iter_text:
                self._conversation.append({"role": "assistant", "content": iter_text})
                self._sync_assistant_message_to_intelligence(iter_text)
                if not benchmark_mode:
                    self._record_event("assistant_response", iter_text)
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
        self._sync_assistant_message_to_intelligence(iter_text)

        # Execute tool calls (parallel when multiple), streaming each completion.
        tool_results: list[AgentEvent] = []
        tool_results_by_id: dict[str, AgentEvent] = {}
        async for result_event in self._execute_tools(pending_tool_calls, iteration):
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
            result_text = result_event.data.get("result_text", "")
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
                        self._sync_user_message_to_intelligence(interrupt_text)
                        yield AgentEvent(
                            type=EventType.THINKING,
                            data={"text": "Received additional user instructions. Adapting plan.\n"},
                            iteration=iteration,
                        )
                except Exception:
                    # Handles both asyncio.QueueEmpty and queue.Empty
                    pass

            state.total_tool_calls += 1

            # Detect repeated failures
            if not result_event.data.get("ok"):
                consecutive_failed_tool_iters += 1
            else:
                consecutive_failed_tool_iters = 0

            if consecutive_failed_tool_iters >= 2:
                current_signature = f"{tc.get('name', '')}:fail"
                if current_signature == repeated_failure_signature:
                    repeated_failure_count += 1
                else:
                    repeated_failure_signature = current_signature
                    repeated_failure_count = 1

            if repeated_failure_count >= 2:
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

        # Context compaction: if approaching budget, compact older messages
        # instead of immediately stopping. This mirrors Claude Code behavior.
        if (
            _HAS_COMPACTION
            and iteration >= 2
            and cumulative_context_tokens >= int(hard_context_budget * 0.80)
            and cumulative_context_tokens < hard_context_budget
        ):
            try:
                compacted = compact_conversation(
                    self._conversation,
                    target_tokens=int(hard_context_budget * 0.60),
                    preserve_recent=8,
                )
                old_len = len(self._conversation)
                self._conversation = compacted
                log.info(
                    "Context compacted: %d -> %d messages at iteration %d",
                    old_len,
                    len(compacted),
                    iteration + 1,
                )
            except Exception as _ce:
                log.debug("Context compaction failed: %s", _ce)

        # Runaway guard: if context is getting too big and we're doing tool loops,
        # proactively stop before we hit hard limits.
        if iteration >= 2 and cumulative_context_tokens >= hard_context_budget:
            runaway_guard_reason = (
                f"Stopped after iteration {iteration + 1}: context approaching hard limit "
                f"({cumulative_context_tokens:,} / {hard_context_budget:,} tokens). "
                f"Consider smaller steps or narrower scope."
            )
            yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
            state.error = runaway_guard_reason
            state.finished = True
            break

    # Delegate post-loop completion (validation, quality gates, final events) to helper
    async for completion_event in handle_post_loop_completion(
        self,
        state,
        prompt_text,
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
