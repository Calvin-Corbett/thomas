"""Resolve one fail-closed runtime policy for each Thomas chat turn."""

from __future__ import annotations

import sqlite3
from typing import Any

from thomas.server.chat_runtime_policy_model import (
    ChatRuntimePolicyError,
    CostRuntimePolicy,
    MemoryRuntimePolicy,
    ModelRuntimePolicy,
    QualityRuntimePolicy,
    ResolvedChatRuntimePolicy,
    _autonomy_level,
    _companion_request,
    _csv_lines,
    model_endpoint_is_local,
)
from thomas.server.chat_tool_policy import (
    PolicyToolRegistryView,
    ToolRuntimePolicy,
    canonical_tool_name,
    tool_policy_from_payload,
)


def resolve_chat_runtime_policy(
    *,
    payload: dict[str, Any],
    session_meta: Any,
    saved_meta: Any,
    config: Any,
    session_id: str,
    user_id: str = "default",
) -> ResolvedChatRuntimePolicy:
    """Resolve one turn's runtime policy with explicit precedence and fail-closed loading."""
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        prefs = PreferencesStore(get_db_path()).get(user_id=user_id, thread_id=session_id)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:  # preferences are an authorization boundary
        raise ChatRuntimePolicyError("Saved chat safety preferences are unavailable") from exc

    advanced = prefs.advanced
    model_prefs = advanced.model
    tool_prefs = advanced.tools
    memory_prefs = advanced.memory
    cost_prefs = advanced.cost
    runtime_prefs = advanced.runtime
    failover_prefs = advanced.failover
    privacy_prefs = advanced.privacy

    models = getattr(config, "models", {}) or {}
    payload_profile = str(payload.get("profile") or payload.get("model") or "").strip()
    if payload_profile and payload_profile not in models:
        raise ValueError(f"unknown profile: {payload_profile}")
    saved_profile = str(getattr(session_meta, "profile", "") or "").strip() if saved_meta is not None else ""
    preferred_profile = str(getattr(model_prefs, "active_profile", "") or "").strip()
    profile = payload_profile or saved_profile or preferred_profile or str(getattr(config, "default_model", "") or "")
    if profile not in models and not payload_profile:
        profile = str(getattr(config, "default_model", "") or "")
    if profile not in models and models:
        profile = next(iter(models))

    payload_model_id = str(payload.get("model_id") or "").strip()
    saved_model_id = str(getattr(session_meta, "model_id", "") or "").strip() if saved_meta is not None else ""
    preferred_model_id = str(getattr(model_prefs, "model_id", "") or "").strip()
    if payload_model_id:
        model_id = payload_model_id
    elif payload_profile:
        model_id = saved_model_id if payload_profile == saved_profile else ""
        if not model_id and payload_profile == preferred_profile:
            model_id = preferred_model_id
    else:
        model_id = saved_model_id or (preferred_model_id if profile == preferred_profile else "")

    default_autonomy = _autonomy_level(getattr(prefs.autonomy, "default_level", None), default=2)
    if "autonomy_level" in payload:
        autonomy = _autonomy_level(payload.get("autonomy_level"), default=default_autonomy)
    elif saved_meta is not None:
        autonomy = int(getattr(session_meta, "autonomy_level", default_autonomy) or default_autonomy)
    else:
        autonomy = default_autonomy

    companion = _companion_request(payload)
    if companion and "autonomy_level" not in payload:
        autonomy = 2
    system_prompt = (
        str(payload.get("system_prompt") or "").strip()
        if "system_prompt" in payload
        else str(getattr(session_meta, "system_prompt", "") or "").strip()
    )
    if companion and not system_prompt:
        from thomas.server.routes.chat_aiohttp_helpers import COMPANION_PHONE_SYSTEM_PROMPT

        system_prompt = COMPANION_PHONE_SYSTEM_PROMPT

    mode = str(payload.get("mode") or getattr(runtime_prefs, "default_mode", "auto") or "auto").strip().casefold()
    token_economy = (
        str(payload.get("token_economy") or getattr(runtime_prefs, "default_token_economy", "optimal") or "optimal")
        .strip()
        .casefold()
    )

    saved_reasoning_effort = (
        str(getattr(session_meta, "reasoning_effort", "") or "").strip() if saved_meta is not None else ""
    )
    reasoning_effort = (
        str(
            payload.get("reasoning_effort")
            or saved_reasoning_effort
            or getattr(model_prefs, "reasoning_effort", "medium")
            or "medium"
        )
        .strip()
        .casefold()
    )
    stop_sequences = tuple(item.strip() for item in str(model_prefs.stop_sequences or "").splitlines() if item.strip())
    failover_profiles = _csv_lines(getattr(cost_prefs, "model_failover_chain", ""))
    model_policy = ModelRuntimePolicy(
        temperature=float(model_prefs.temperature),
        top_p=float(model_prefs.top_p),
        max_output_tokens=int(model_prefs.max_output_tokens),
        reasoning_effort=reasoning_effort,
        frequency_penalty=float(model_prefs.frequency_penalty),
        presence_penalty=float(model_prefs.presence_penalty),
        deterministic_seed=model_prefs.deterministic_seed,
        json_mode=bool(model_prefs.json_mode),
        stop_sequences=stop_sequences,
        max_retries=max(1, int(cost_prefs.max_retries) + 1),
        retry_backoff_s=max(0.0, float(cost_prefs.retry_backoff_ms) / 1000.0),
        failover_enabled=bool(failover_prefs.enabled and failover_prefs.chat_auto_failover),
        failover_on_auth_error=bool(failover_prefs.fallback_on_auth_error),
        failover_cooldown_s=max(0, int(failover_prefs.cooldown_seconds)),
        failover_profiles=failover_profiles,
    )

    local_only = bool(privacy_prefs.local_only_mode)
    request_network = payload.get("allow_network", payload.get("external_access", True))
    request_allows_network = request_network is not False and str(request_network).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
        "deny",
        "denied",
        "blocked",
    }
    tools_policy = ToolRuntimePolicy(
        allow_shell=bool(tool_prefs.allow_shell),
        allow_file_write=bool(tool_prefs.allow_file_write),
        allow_network=bool(tool_prefs.allow_network and request_allows_network and not local_only),
        allow_browser=bool(tool_prefs.allow_browser and not local_only),
        allow_channels=bool(tool_prefs.allow_channels and not local_only),
        allow_git=bool(tool_prefs.allow_git),
        require_command_approval=bool(tool_prefs.require_command_approval),
        tool_timeout_s=int(tool_prefs.tool_timeout_s),
        max_parallel_tools=int(tool_prefs.max_parallel_tools),
        allowed_paths=_csv_lines(tool_prefs.allowed_paths),
        blocked_commands=_csv_lines(tool_prefs.blocked_commands, lower=True),
    )

    base_memory = bool(
        prefs.memory.thread_enabled if prefs.memory.thread_enabled is not None else prefs.memory.enabled_global
    )
    if "memory" in payload:
        requested_memory = payload.get("memory")
    elif saved_meta is not None:
        requested_memory = getattr(session_meta, "memory_enabled", True)
    else:
        requested_memory = True
    request_memory_enabled = requested_memory is not False and str(requested_memory).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }
    memory_policy = MemoryRuntimePolicy(
        enabled=bool(base_memory and request_memory_enabled),
        include_thread=bool(memory_prefs.include_thread_memory),
        include_global=bool(memory_prefs.include_global_memory),
        include_profile=bool(memory_prefs.include_profile_memory),
        pins_only=bool(memory_prefs.pins_only),
        retrieval_top_k=int(memory_prefs.retrieval_top_k),
        decay_half_life_hours=float(memory_prefs.decay_half_life_hours),
        context_budget=int(memory_prefs.max_pack_tokens),
        pinned_context=str(memory_prefs.pinned_context or "").strip(),
    )

    from thomas.preferences.profile import (
        normalize_profile_type,
        normalize_review_depth,
        profile_prefers_non_coder_mode,
    )

    profile_type = normalize_profile_type(getattr(prefs.profile, "profile_type", None), default="adaptive")
    onboarding_answers = getattr(prefs.onboarding, "answers", None)
    non_coder = bool(
        profile_type == "non_coder"
        or profile_prefers_non_coder_mode(
            prefs.profile,
            onboarding_answers=onboarding_answers if isinstance(onboarding_answers, dict) else {},
        )
    )
    if profile_type == "adaptive" and non_coder:
        profile_type = "non_coder"
    review_depth = normalize_review_depth(getattr(prefs.profile, "review_depth", None), default="adaptive")
    if review_depth == "adaptive" and non_coder:
        review_depth = "simple"

    quality_policy = QualityRuntimePolicy(
        enforce=True if non_coder else bool(runtime_prefs.quality_enforce),
        require_verification_for_coding=True
        if non_coder
        else bool(runtime_prefs.quality_require_verification_for_coding),
        require_tests_for_code_edits=True if non_coder else bool(runtime_prefs.quality_require_tests_for_code_edits),
        require_monolith_guard_for_coding=True
        if non_coder
        else bool(runtime_prefs.quality_require_monolith_guard_for_coding),
        max_agent_iterations=max(0, int(runtime_prefs.max_agent_iterations)),
    )
    cost_policy = CostRuntimePolicy(
        session_token_budget=int(cost_prefs.session_token_budget),
        daily_token_budget=int(cost_prefs.daily_token_budget),
        throttle_on_budget=bool(cost_prefs.throttle_on_budget),
    )

    resolved = ResolvedChatRuntimePolicy(
        profile=profile,
        model_id=model_id,
        autonomy_level=autonomy,
        mode=mode,
        token_economy=token_economy,
        system_prompt=system_prompt,
        profile_type=profile_type,
        review_depth=review_depth,
        non_coder_profile=non_coder,
        local_only=local_only,
        model=model_policy,
        tools=tools_policy,
        memory=memory_policy,
        quality=quality_policy,
        cost=cost_policy,
    )
    resolved.assert_profile_allowed(config)
    return resolved


__all__ = [
    "ChatRuntimePolicyError",
    "CostRuntimePolicy",
    "MemoryRuntimePolicy",
    "ModelRuntimePolicy",
    "PolicyToolRegistryView",
    "QualityRuntimePolicy",
    "ResolvedChatRuntimePolicy",
    "ToolRuntimePolicy",
    "canonical_tool_name",
    "model_endpoint_is_local",
    "resolve_chat_runtime_policy",
    "tool_policy_from_payload",
]
