"""Post-loop completion and quality validation for agent runs."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.completion_gate import (
    GATE_BLOCK,
    GATE_DEMAND_GIVE_UP,
    GATE_GIVE_UP,
    build_give_up_demand_prompt,
    evaluate_completion_gate,
)
from thomas.core.config import load_config
from thomas.core.events import AgentEvent
from thomas.core.rules_of_road import build_remediation_prompt, evaluate_rules

if TYPE_CHECKING:
    from thomas.agent.loop import AgentLoop
    from thomas.agent.loop_core import LoopState
    from thomas.core.route import Route

log = logging.getLogger(__name__)


async def handle_post_loop_completion(
    self: AgentLoop,
    state: LoopState,
    prompt_text: str,
    route: Route,
    job_type: str | None,
    mode: str,
    tools_policy: str,
    applied_token_economy: str,
    max_iterations: int | None,
    _quality_retry_count: int,
    _quality_carry_forward_events: list[dict[str, Any]] | None,
    # Loop state/metrics
    usage_before: dict[str, Any],
    stream_usage: dict[str, Any],
    iter_token_estimates: list[int],
    effective_mode: str,
    peak_context_tokens: int,
    memory_tokens: int,
    tool_chars_total: int,
    tool_chars_kept: int,
    effective_tools_policy: str,
    autonomy_name: str,
    route_input_source: str,
    followup_suppressed_count: int,
    thought_leak_suppressed_count: int,
    full_auto_reprompt_count: int,
    clarification_question_cap: int,
    clarification_questions_asked: int,
    clarification_reprompt_count: int,
    best_practice_gate_active: bool,
    best_practice_gate_source: str,
    code_output_guard_reprompts: int,
    code_output_guard_last_issue: str,
    strict_issue_ownership: bool,
    high_prompt_spend_fail_iters: int,
    token_economy_meta: dict[str, Any],
    runtime_skills_payload: dict[str, Any],
    provider_tpm_budget: int,
    provider_prompt_window: list[tuple[float, int]],
    mode_context_budget: int,
    hard_context_budget: int | None,
    emergency_context_budget: int,
    iter_prompt_warn_cap: int,
    iter_prompt_hard_cap: int | None,
    iter_prompt_spends: list[int],
    cumulative_context_tokens: int,
    runaway_guard_reason: str,
    provider_tpm_limit: int,
    provider_prompt_tokens_last_minute: int,
    provider_tpm_wait_events: int,
    provider_tpm_wait_seconds: float,
    quality_tool_events: list[dict[str, Any]],
    prune_window_func,
):
    """Post-loop validation, quality gates, and final event generation."""
    # Cleanup: Auto-capture research into library if enabled
    if prompt_text and state.text_response:
        try:
            self._auto_capture_research(
                route=route,
                query=prompt_text,
                answer=state.text_response,
                job_type=job_type,
            )
        except Exception as e:  # REVIEWED: log-and-continue
            log.debug("Research auto-capture failed: %s", e)

    # Build token report
    usage_after = self._session_usage_snapshot()
    usage_obj = self._usage_delta(usage_before, usage_after)
    if usage_obj["total_tokens"] <= 0 and stream_usage["total_tokens"] > 0:
        usage_obj = dict(stream_usage)
    avg_context = int(sum(iter_token_estimates) / len(iter_token_estimates)) if iter_token_estimates else 0
    token_report = self._build_token_report(
        prompt_text=prompt_text,
        usage_obj=usage_obj,
        mode=effective_mode,
        iterations=state.iteration + 1,
        peak_context_tokens=peak_context_tokens,
        avg_context_tokens=avg_context,
        memory_tokens=memory_tokens,
        tool_chars_total=tool_chars_total,
        tool_chars_kept=tool_chars_kept,
    )

    # Add route and policy info to token report
    token_report["route"] = route.to_dict()
    token_report["effective_tools_policy"] = effective_tools_policy
    token_report["autonomy_level"] = int(self._autonomy_level)
    token_report["autonomy_name"] = autonomy_name

    # Add continuity metadata
    token_report["continuity"] = {
        "route_input_source": route_input_source,
        "followup_suppressed_count": int(followup_suppressed_count),
        "thought_leak_suppressed_count": int(thought_leak_suppressed_count),
        "full_auto_reprompt_count": int(full_auto_reprompt_count),
        "clarification_question_cap": int(clarification_question_cap),
        "clarification_questions_asked": int(clarification_questions_asked),
        "clarification_reprompt_count": int(clarification_reprompt_count),
        "best_practice_gate_active": bool(best_practice_gate_active),
        "best_practice_gate_source": str(best_practice_gate_source),
        "profile_type": str(self._profile_type),
        "code_output_guard_reprompts": int(code_output_guard_reprompts),
        "code_output_guard_last_issue": str(code_output_guard_last_issue),
        "strict_issue_ownership": bool(strict_issue_ownership),
        "high_prompt_spend_fail_iters": int(high_prompt_spend_fail_iters),
    }
    token_report["token_economy"] = dict(token_economy_meta)
    token_report["skills"] = dict(runtime_skills_payload)

    # Add budget/performance metrics
    if provider_tpm_budget > 0:
        prune_window_func(time.monotonic())
        provider_prompt_tokens_last_minute = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))

    token_report["run_budget"] = {
        "token_economy": str(applied_token_economy),
        "mode_context_budget": int(mode_context_budget),
        "hard_context_budget": int(hard_context_budget) if hard_context_budget is not None else None,
        "emergency_context_budget": int(emergency_context_budget),
        "iteration_prompt_warn_cap": int(iter_prompt_warn_cap),
        "iteration_prompt_hard_cap": int(iter_prompt_hard_cap) if iter_prompt_hard_cap is not None else None,
        "max_iteration_prompt_spend": int(max(iter_prompt_spends) if iter_prompt_spends else 0),
        "high_prompt_spend_fail_iters": int(high_prompt_spend_fail_iters),
        "cumulative_context_tokens": int(cumulative_context_tokens),
        "runaway_guard_triggered": bool(runaway_guard_reason),
        "runaway_guard_reason": str(runaway_guard_reason or ""),
        "provider_tpm_limit": int(provider_tpm_limit) if provider_tpm_limit > 0 else None,
        "provider_tpm_budget": int(provider_tpm_budget) if provider_tpm_budget > 0 else None,
        "provider_prompt_tokens_last_minute": int(provider_prompt_tokens_last_minute),
        "provider_tpm_wait_events": int(provider_tpm_wait_events),
        "provider_tpm_wait_seconds": round(float(provider_tpm_wait_seconds), 3),
    }

    # Add warning flags and suggestions
    if runaway_guard_reason:
        token_report.setdefault("flags", []).append(
            {
                "kind": "runaway_guard",
                "severity": "high",
                "detail": "Run was stopped by automatic token waste protection.",
            }
        )
        token_report.setdefault("suggestions", []).append(
            "Retry in a fresh chat or with tighter scope to reduce context growth."
        )
    if iter_prompt_spends and max(iter_prompt_spends) >= int(iter_prompt_warn_cap):
        token_report.setdefault("flags", []).append(
            {
                "kind": "iteration_prompt_spend",
                "severity": "medium",
                "detail": (
                    "One or more iterations used unusually high prompt tokens; "
                    "review tool loops, memory scope, and mode/economy settings."
                ),
            }
        )
        token_report.setdefault("suggestions", []).append(
            "If this repeats, narrow scope or lower memory/tool breadth to avoid oversized prompt rebuilds."
        )

    # Evaluate rules of road
    _low_intent_skip_quality = {"casual_chat", "personal_context", "assistant_meta", "general"}
    cfg_errors: list[str] = []
    cfg_unknown: list[str] = []
    if str(route.path or "") not in _low_intent_skip_quality:
        try:
            cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
            loaded_cfg = load_config(cfg_path)
            cfg_errors = loaded_cfg.validate()
            cfg_unknown = list(loaded_cfg.unknown_core_keys)
        except Exception as e:  # REVIEWED: log-and-continue
            cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

    quality_cfg = getattr(self.config, "quality", None)
    quality_enabled = bool(getattr(quality_cfg, "enabled", True))
    quality_enforce = bool(getattr(quality_cfg, "enforce", True))
    quality_max_retries = max(0, min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)))
    require_verify = bool(getattr(quality_cfg, "require_verification_for_coding", True))
    require_tests = bool(getattr(quality_cfg, "require_tests_for_code_edits", False))

    combined_quality_events = list(_quality_carry_forward_events or []) + quality_tool_events
    rules_report = evaluate_rules(
        route_path=str(route.path or ""),
        prompt_text=prompt_text,
        response_text=state.text_response,
        tool_events=combined_quality_events,
        requested_job_type=job_type,
        config_errors=cfg_errors,
        unknown_core_keys=cfg_unknown,
        require_verification_for_coding=require_verify,
        require_tests_for_code_edits=require_tests,
        require_monolith_guard_for_coding=bool(getattr(quality_cfg, "require_monolith_guard_for_coding", True)),
        strict_issue_ownership=bool(strict_issue_ownership),
        skill_required_checks=list(runtime_skills_payload.get("required_checks") or []),
        attempt=int(_quality_retry_count),
        repo_root=Path.cwd(),
    )
    token_report["rules_of_road"] = rules_report

    issue_ownership_signals = rules_report.get("signals") or {}
    issue_ownership_blocked = bool(
        bool(issue_ownership_signals.get("strict_issue_ownership"))
        and bool(issue_ownership_signals.get("unresolved_issue_detected"))
    )

    # Quality-gate retries are for action routes only
    quality_required = not bool(rules_report.get("passed", False))
    if strict_issue_ownership:
        quality_max_retries = max(quality_max_retries, 2)
    quality_retry_enabled = strict_issue_ownership or str(route.path or "") not in _low_intent_skip_quality
    if (
        quality_required
        and _quality_retry_count < quality_max_retries
        and ((quality_enabled and quality_enforce) or strict_issue_ownership)
        and not bool(state.error)
        and quality_retry_enabled
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

    if (
        quality_required
        and strict_issue_ownership
        and issue_ownership_blocked
        and _quality_retry_count >= quality_max_retries
        and not bool(state.error)
    ):
        block_error = (
            "Issue-ownership quality gate blocked completion: "
            "user-facing text still appears to describe unresolved issues or workaround-only work."
        )
        yield AgentEvent.agent_error(block_error, iteration=state.iteration)
        state.error = block_error
        return

    # Errors and exhausted pass budgets are incomplete outcomes. Never append a
    # success event after an AGENT_ERROR; Code and Work must not present partial
    # changes as finished work.
    if state.error:
        return

    # Completion gate: a bare AGENT_DONE on failed validation is rejected.
    # The run must either fix the failing checks or return an explicit
    # structured give-up with a diagnosis (see thomas.agent.completion_gate).
    gate_decision = evaluate_completion_gate(
        validation_passed=bool(rules_report.get("passed", False)),
        response_text=state.text_response,
        gate_active=bool(((quality_enabled and quality_enforce) or strict_issue_ownership) and quality_retry_enabled),
        attempt=int(_quality_retry_count),
        max_retries=int(quality_max_retries),
    )
    token_report["completion_gate"] = gate_decision.to_payload()

    if gate_decision.outcome == GATE_DEMAND_GIVE_UP:
        retry_job_type = str(job_type or rules_report.get("job_type") or "").strip().lower() or None
        async for gate_event in self.run(
            build_give_up_demand_prompt(rules_report),
            mode=mode,
            tools_policy=tools_policy,
            token_economy=applied_token_economy,
            max_iterations=max_iterations,
            job_type=retry_job_type,
            _quality_retry_count=_quality_retry_count + 1,
            _quality_carry_forward_events=combined_quality_events,
        ):
            yield gate_event
        return

    if gate_decision.outcome == GATE_BLOCK:
        block_error = f"Completion gate blocked AGENT_DONE: {gate_decision.reason}"
        yield AgentEvent.agent_error(block_error, iteration=state.iteration)
        state.error = block_error
        return

    # Yield final completion event. A diagnosed give-up completes distinctly
    # from success so callers can tell the outcomes apart.
    done_event = AgentEvent.agent_done(
        text=state.text_response,
        iterations=state.iteration + 1,
        tool_calls=state.total_tool_calls,
        usage=usage_obj,
        token_report=token_report,
    )
    if gate_decision.outcome == GATE_GIVE_UP and gate_decision.diagnosis is not None:
        done_event.data["gave_up"] = True
        done_event.data["give_up_diagnosis"] = gate_decision.diagnosis.to_payload()
    yield done_event

    # Auto-generate reusable tool from completed task (successes only; a
    # diagnosed give-up is not a reusable success pattern)
    if state.text_response and state.total_tool_calls > 0 and gate_decision.outcome != GATE_GIVE_UP:
        try:
            from thomas.core.tool_factory import get_tool_factory

            factory = get_tool_factory()
            tool_schema = factory.create_tool_from_task(
                task_description=prompt_text,
                steps_taken=self._conversation[-10:],  # recent context
                code_written=None,  # could extract from tool results
                outcome="success" if not state.error else "error",
            )
            if tool_schema:
                factory.register(tool_schema)
                log.debug("ToolFactory: registered tool '%s' from task", tool_schema.name)
        except Exception as e:  # REVIEWED: log-and-continue
            log.debug("ToolFactory: failed to create tool from task: %s", e)
