"""Turn setup and context preparation for the main agent execution loop."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.acceptance_runtime import begin_contract
from thomas.agent.response_tone import (
    best_practice_default_hint,
    simplified_review_default_hint,
)
from thomas.agent.routing import PATH_CODING, PATH_MODEL_OWNED, RouteDecision
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
from thomas.core.autonomy import autonomy_spec
from thomas.core.token_economy import (
    RuntimeOverheadPolicy,
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


@dataclass
class ExecutionSetup:
    """Read-only turn policy plus context assembled before model iteration."""

    prompt_text: str
    request_text: str
    routing_text: str
    benchmark_mode: bool
    current_job_type: str
    route: RouteDecision
    route_input_source: str
    prompt_route_path: str
    autonomy_name: str
    effective_mode: str
    applied_token_economy: str
    token_economy_meta: dict[str, Any]
    overhead_policy: RuntimeOverheadPolicy
    strict_issue_ownership: bool
    best_practice_gate_active: bool
    best_practice_gate_source: str
    review_quality_hint: str
    best_practice_hint: str
    code_output_validation_enabled: bool
    runtime_skills_context: str
    runtime_skills_payload: dict[str, Any]
    usage_before: dict[str, int]
    stream_usage: dict[str, int]
    max_iter: int
    effective_tools_policy: str
    tool_specs: list[dict[str, Any]] | None
    preserve_first: int
    preserve_last: int
    history_token_cap: int
    mode_context_budget: int
    hard_context_budget: int
    emergency_context_budget: int
    iter_prompt_warn_cap: int
    iter_prompt_hard_cap: int
    provider_tpm_limit: int
    provider_tpm_budget: int
    memory_text: str = ""
    continuity_hint: str = ""
    test_visibility_hint: str = ""
    library_text: str = ""
    memory_tokens: int = 0
    contract_block: str = ""


def prepare_execution_setup(
    self: AgentLoop,
    prompt: Any,
    *,
    intent_text: str | None,
    mode: str,
    tools_policy: str,
    token_economy: str,
    max_iterations: int | None,
    job_type: str | None,
) -> ExecutionSetup:
    """Resolve routing, runtime policy, skills, tools, and numeric budgets."""
    prompt_text = prompt if isinstance(prompt, str) else ""
    if isinstance(prompt, list):
        for part in prompt:
            if isinstance(part, dict) and part.get("type") == "text":
                prompt_text += str(part.get("text", "")) + "\n"
        prompt_text = prompt_text.strip()
    request_text = str(intent_text) if intent_text is not None else prompt_text
    routing_text = request_text
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
    effective_mode = route.mode
    applied_token_economy = normalize_token_economy_level(token_economy)
    token_economy_meta = build_token_economy_meta(token_economy, applied_token_economy)
    overhead_policy = runtime_overhead_policy(applied_token_economy)
    self._memory_include_profile_economy_cap = bool(overhead_policy.include_memory_profile)
    strict_issue_ownership = bool(
        self._non_coder_profile or str(self._profile_type or "").strip().lower() in {"non_coder", "non-coder"}
    )
    include_best_practices = overhead_policy.include_best_practice_hint
    best_practice_gate_active = bool(include_best_practices and self._non_coder_profile)
    review_quality_hint = (
        simplified_review_default_hint(
            self._review_depth,
            non_coder_profile=bool(self._non_coder_profile),
        )
        if overhead_policy.include_review_quality_hint
        else ""
    )
    best_practice_hint = (
        best_practice_default_hint()
        if overhead_policy.include_best_practice_hint and bool(self._non_coder_profile)
        else ""
    )

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
    skills_mode = str(overhead_policy.runtime_skills_mode or "off").strip().lower()
    if skills_mode in {"auto", "explicit"}:
        try:
            runtime_skills = resolve_runtime_skills(
                self.config,
                prompt_text=routing_text,
                relevance_text=routing_text,
                route_path=prompt_route_path,
                cwd=Path.cwd(),
            )
            runtime_skills_context = format_runtime_skills_context(runtime_skills)
            runtime_skills_payload = runtime_skills.to_event_payload()
        except Exception as exc:  # REVIEWED: optional plugin failures are non-fatal
            log.warning("Runtime skills resolution failed: %s", exc)
            runtime_skills_payload["error"] = f"{type(exc).__name__}: {exc}"

    configured_iterations = getattr(self.config, "max_agent_iterations", None)
    configured_max_iter = coerce_base_iterations(configured_iterations)
    max_iter = (
        coerce_base_iterations(max_iterations)
        if max_iterations is not None
        else compute_max_passes(applied_token_economy, configured_max_iter)
    )
    effective_tools_policy = route.tools_policy
    forced_tools_policy = autonomy.force_tools_policy
    if forced_tools_policy == "never":
        effective_tools_policy = "never"
    elif tools_policy == "auto" and forced_tools_policy in {"auto", "always"}:
        effective_tools_policy = str(forced_tools_policy)
    tool_specs = self._select_tools(
        routing_text,
        policy=effective_tools_policy,
        route=route,
    )
    preserve_first, preserve_last = self._history_preserve_counts(route)
    history_token_cap = self._history_token_cap(route)
    mode_context_budget, hard_context_budget, emergency_context_budget = loop_context_budgets(
        applied_token_economy, effective_mode
    )
    iter_prompt_warn_cap, iter_prompt_hard_cap = loop_iteration_prompt_caps(
        applied_token_economy,
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
        provider_tpm_budget = max(1, int(provider_tpm_limit * provider_tpm_headroom))

    return ExecutionSetup(
        prompt_text=prompt_text,
        request_text=request_text,
        routing_text=routing_text,
        benchmark_mode=current_job_type == "benchmark",
        current_job_type=current_job_type,
        route=route,
        route_input_source="current_turn",
        prompt_route_path=prompt_route_path,
        autonomy_name=str(autonomy.name),
        effective_mode=effective_mode,
        applied_token_economy=applied_token_economy,
        token_economy_meta=token_economy_meta,
        overhead_policy=overhead_policy,
        strict_issue_ownership=strict_issue_ownership,
        best_practice_gate_active=best_practice_gate_active,
        best_practice_gate_source=("profile_non_coder" if bool(self._non_coder_profile) else ""),
        review_quality_hint=review_quality_hint,
        best_practice_hint=best_practice_hint,
        code_output_validation_enabled=current_job_type == "benchmark",
        runtime_skills_context=runtime_skills_context,
        runtime_skills_payload=runtime_skills_payload,
        usage_before=self._session_usage_snapshot(),
        stream_usage=self._normalize_usage(0, 0, 0),
        max_iter=max_iter,
        effective_tools_policy=effective_tools_policy,
        tool_specs=tool_specs,
        preserve_first=preserve_first,
        preserve_last=preserve_last,
        history_token_cap=history_token_cap,
        mode_context_budget=mode_context_budget,
        hard_context_budget=hard_context_budget,
        emergency_context_budget=emergency_context_budget,
        iter_prompt_warn_cap=iter_prompt_warn_cap,
        iter_prompt_hard_cap=iter_prompt_hard_cap,
        provider_tpm_limit=provider_tpm_limit,
        provider_tpm_budget=provider_tpm_budget,
    )
