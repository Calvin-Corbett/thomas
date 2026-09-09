"""Policy-aware model-client initialization for Chat V2."""

from __future__ import annotations

from typing import Any

from thomas.server.routes.chat_v2_support import _get_or_create_session_llm


async def initialize_chat_v2_llm(
    app: Any,
    *,
    config: Any,
    runtime_policy: Any,
    session_id: str,
    requested_model_id: str,
    requested_reasoning_effort: str,
) -> tuple[Any, Any, str]:
    profile = runtime_policy.profile
    if not profile or not hasattr(config, "models") or profile not in config.models:
        profile = getattr(config, "default_model", "")
    model_cfg = runtime_policy.model.apply(
        config.get_model(profile),
        model_id=requested_model_id,
        reasoning_effort=requested_reasoning_effort,
    )
    configured_failovers = list(config.failover_chain(profile)) if hasattr(config, "failover_chain") else []
    failover_cfgs = runtime_policy.filter_failovers(config, configured_failovers)
    llm, lock = await _get_or_create_session_llm(
        app,
        session_id=session_id,
        model_cfg=model_cfg,
        fallback_cfgs=list(failover_cfgs or []),
        failover_enabled=bool(runtime_policy.model.failover_enabled and failover_cfgs),
        failover_cooldown_s=runtime_policy.model.failover_cooldown_s,
        failover_on_auth_error=runtime_policy.model.failover_on_auth_error,
        max_retries=runtime_policy.model.max_retries,
        base_retry_delay_s=runtime_policy.model.retry_backoff_s,
        request_overrides=runtime_policy.model.request_overrides,
    )
    return llm, lock, profile


__all__ = ["initialize_chat_v2_llm"]
