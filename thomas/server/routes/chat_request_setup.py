"""Setup and configuration for chat requests.

This module extracts preference loading, session management, and model resolution
from the main execute_chat_request function to keep it under 800 lines.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from aiohttp import web

from thomas.core.autonomy import clamp_autonomy_level, parse_autonomy_level
from thomas.core.config import AppConfig
from thomas.server.app_keys import (
    APP_ENGINE_MANAGER,
    APP_SESSIONS,
    APP_TASK_LEDGER,
    ChatSession,
)

from .chat_aiohttp_helpers import (
    COMPANION_PHONE_SYSTEM_PROMPT,
    ChatRouteDeps,
    _resolve_app_value,
)

log = logging.getLogger(__name__)


async def setup_chat_request(
    request: web.Request,
    payload: dict[str, Any],
    sid: str,
    cfg: AppConfig,
    fast_mode: bool,
    deps: ChatRouteDeps,
) -> dict[str, Any]:
    """Set up chat request configuration and preferences.

    Returns a dict with all setup state needed by execute_chat_request's
    main orchestration logic.
    """

    memory_enabled_for_turn = True
    memory_retrieval_scope = "thread"
    memory_include_thread_pref: bool | None = None
    memory_include_global_pref: bool | None = None
    memory_include_profile_pref: bool | None = None
    memory_pins_only_pref: bool | None = None
    memory_max_results_pref: int | None = None
    memory_decay_half_life_hours_pref: float | None = None
    memory_auto_compact_enabled_pref: bool | None = None
    memory_auto_compact_episode_threshold_pref: int | None = None
    memory_auto_compact_min_interval_hours_pref: float | None = None
    memory_auto_optimize_enabled_pref: bool | None = None
    memory_auto_optimize_waste_threshold_pref: float | None = None

    def _resolve_default_model_pair() -> tuple[str, str]:
        try:
            from os import environ

            from thomas.core.model_resolution import resolve_effective_model
            from thomas.preferences.store import get_db_path

            resolved_profile, resolved_model_id = resolve_effective_model(
                cfg,
                env_profile=str(environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
                user_id="default",
                db_path=get_db_path(),
            )
            if resolved_profile in cfg.models:
                return resolved_profile, str(resolved_model_id or "")
        except Exception:
            pass
        fallback = str(cfg.default_model or "").strip()
        if fallback not in cfg.models and cfg.models:
            fallback = next(iter(cfg.models))
        return fallback, ""

    sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
    if sid not in sessions:
        # Try to recover conversation from persisted chat on disk.
        recovered_conversation: list[dict[str, Any]] = []
        try:
            chat_path = deps.chat_file_for(sid)
            if chat_path.exists():
                saved = deps.read_chat_from_disk(chat_path)
                if saved and isinstance(saved.get("messages"), list):
                    for m in saved["messages"]:
                        if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                            recovered_conversation.append({"role": m["role"], "content": str(m.get("content", ""))})
                    if recovered_conversation:
                        log.info(
                            "Recovered %d messages from disk for stale session %s",
                            len(recovered_conversation),
                            sid[:12],
                        )
        except Exception as e:
            log.debug("Session recovery from disk failed for %s: %s", sid[:12], e)
        default_profile, default_model_id = _resolve_default_model_pair()
        session_profile = default_profile if default_profile in cfg.models else str(cfg.default_model)
        sessions[sid] = ChatSession(
            id=sid,
            conversation=recovered_conversation,
            profile=session_profile,
            model_id=(default_model_id or None),
            autonomy_level=2,
        )
    session: ChatSession = sessions[sid]

    # Load preferences
    if fast_mode:
        runtime_prefs = None
        runtime_prefs_saved = False
        advanced_prefs = None
        advanced_privacy = None
        advanced_runtime = None
        advanced_cost = None
        advanced_tools = None
        advanced_model = None
        advanced_failover = None
        advanced_memory = None
        profile_prefs = None
        onboarding_prefs = None
        onboarding_answers = {}
        resolved_profile_type = "adaptive"
        non_coder_profile = False
        resolved_review_depth = "adaptive"
        # Fast mode keeps latency-focused tuning lightweight, but must still
        # enforce persisted safety/privacy/tool policies.
        try:
            from thomas.preferences.store import PreferencesStore, get_db_path

            prefs_store = PreferencesStore(get_db_path())
            runtime_prefs = prefs_store.get(user_id="default", thread_id=sid)
            try:
                with prefs_store._lock, prefs_store._connect() as prefs_conn:
                    runtime_prefs_saved = (
                        prefs_conn.execute(
                            "SELECT 1 FROM preferences WHERE user_id = ?",
                            ("default",),
                        ).fetchone()
                        is not None
                    )
            except Exception:
                runtime_prefs_saved = False
        except Exception:
            runtime_prefs = None
            runtime_prefs_saved = False
        advanced_prefs = getattr(runtime_prefs, "advanced", None)
        advanced_privacy = getattr(advanced_prefs, "privacy", None)
        advanced_tools = getattr(advanced_prefs, "tools", None)
    else:
        try:
            from thomas.preferences.store import PreferencesStore, get_db_path

            prefs_store = PreferencesStore(get_db_path())
            runtime_prefs = prefs_store.get(user_id="default", thread_id=sid)
            try:
                with prefs_store._lock, prefs_store._connect() as prefs_conn:
                    runtime_prefs_saved = (
                        prefs_conn.execute(
                            "SELECT 1 FROM preferences WHERE user_id = ?",
                            ("default",),
                        ).fetchone()
                        is not None
                    )
            except Exception:
                runtime_prefs_saved = False
        except Exception:
            runtime_prefs = None
            runtime_prefs_saved = False
        advanced_prefs = getattr(runtime_prefs, "advanced", None)
        advanced_privacy = getattr(advanced_prefs, "privacy", None)
        advanced_runtime = getattr(advanced_prefs, "runtime", None)
        advanced_cost = getattr(advanced_prefs, "cost", None)
        advanced_tools = getattr(advanced_prefs, "tools", None)
        advanced_model = getattr(advanced_prefs, "model", None)
        advanced_failover = getattr(advanced_prefs, "failover", None)
        advanced_memory = getattr(advanced_prefs, "memory", None)
        profile_prefs = getattr(runtime_prefs, "profile", None)
        onboarding_prefs = getattr(runtime_prefs, "onboarding", None)
        onboarding_answers = getattr(onboarding_prefs, "answers", None)
        if not isinstance(onboarding_answers, dict):
            onboarding_answers = {}

        from thomas.preferences.profile import (
            normalize_profile_type,
            normalize_review_depth,
            profile_prefers_non_coder_mode,
        )

        resolved_profile_type = normalize_profile_type(
            getattr(profile_prefs, "profile_type", None),
            default="adaptive",
        )
        non_coder_profile = bool(
            resolved_profile_type == "non_coder"
            or profile_prefers_non_coder_mode(
                profile_prefs,
                onboarding_answers=onboarding_answers,
            )
        )
        if resolved_profile_type == "adaptive" and non_coder_profile:
            resolved_profile_type = "non_coder"
        resolved_review_depth = normalize_review_depth(
            getattr(profile_prefs, "review_depth", None),
            default="adaptive",
        )
        if resolved_review_depth == "adaptive" and non_coder_profile:
            resolved_review_depth = "simple"

        memory_prefs = getattr(runtime_prefs, "memory", None)
        thread_memory_enabled = getattr(memory_prefs, "thread_enabled", None)
        if thread_memory_enabled is None:
            # FIX (2026-03-18): Default to True when no preference exists.
            # Previously, missing/malformed prefs could silently kill memory
            # on new sessions or after page refresh. Memory should ALWAYS
            # be on unless the user explicitly disables it.
            _global_mem = getattr(memory_prefs, "enabled_global", None)
            memory_enabled_for_turn = bool(_global_mem) if _global_mem is not None else True
        else:
            memory_enabled_for_turn = bool(thread_memory_enabled)
        memory_include_thread_pref = bool(getattr(advanced_memory, "include_thread_memory", True))
        memory_include_global_pref = bool(getattr(advanced_memory, "include_global_memory", True))
        memory_include_profile_pref = bool(getattr(advanced_memory, "include_profile_memory", True))
        memory_pins_only_pref = bool(getattr(advanced_memory, "pins_only", False))
        memory_max_results_pref = int(getattr(advanced_memory, "retrieval_top_k", 8) or 8)
        memory_decay_half_life_hours_pref = float(getattr(advanced_memory, "decay_half_life_hours", 240.0) or 240.0)
        memory_auto_compact_enabled_pref = bool(getattr(advanced_memory, "auto_compact_enabled", True))
        memory_auto_compact_episode_threshold_pref = int(
            getattr(advanced_memory, "auto_compact_episode_threshold", 2000) or 2000
        )
        memory_auto_compact_min_interval_hours_pref = float(
            getattr(advanced_memory, "auto_compact_min_interval_hours", 24.0) or 24.0
        )
        memory_auto_optimize_enabled_pref = bool(getattr(advanced_memory, "auto_optimize_enabled", True))
        memory_auto_optimize_waste_threshold_pref = float(
            getattr(advanced_memory, "auto_optimize_waste_threshold", 0.22) or 0.22
        )
        memory_auto_optimize_min_interval_hours_pref = float(
            getattr(advanced_memory, "auto_optimize_min_interval_hours", 12.0) or 12.0
        )

    async def _apply_usage_budget(used_tokens: int) -> dict[str, Any] | None:
        if advanced_cost is None:
            return None
        used = max(0, int(used_tokens or 0))
        prior = int(getattr(session, "session_token_spend", 0) or 0)
        session_tokens_used = max(0, prior + used)
        session.session_token_spend = int(session_tokens_used)
        session_budget = int(getattr(advanced_cost, "session_token_budget", 0) or 0)
        daily_budget = int(getattr(advanced_cost, "daily_token_budget", 0) or 0)
        return {
            "session": {
                "used_tokens": int(session_tokens_used),
                "budget_tokens": int(session_budget),
                "remaining_tokens": max(0, int(session_budget) - int(session_tokens_used)),
            },
            "daily": {
                "used_tokens": int(session_tokens_used),
                "budget_tokens": int(daily_budget),
                "remaining_tokens": max(0, int(daily_budget) - int(session_tokens_used)),
            },
        }

    profile_payload = str(payload.get("profile") or "").strip()
    model_payload = str(payload.get("model") or "").strip()
    default_profile, default_model_id = _resolve_default_model_pair()
    profile = str(profile_payload or model_payload or session.profile).strip()
    explicit_profile_requested = bool(profile_payload or model_payload)
    if profile not in cfg.models:
        if explicit_profile_requested:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
        # Graceful fallback: try session profile -> default -> first available
        _fb = default_profile if default_profile in cfg.models else session.profile
        if _fb not in cfg.models:
            _fb = session.profile if session.profile in cfg.models else cfg.default_model
        if _fb not in cfg.models and cfg.models:
            _fb = next(iter(cfg.models))
        if _fb in cfg.models:
            log.warning("Unknown profile '%s', falling back to '%s'", profile, _fb)
            profile = _fb
        else:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile} (no models configured)")
    if bool(getattr(advanced_privacy, "local_only_mode", False)) and profile != "local":
        raise web.HTTPForbidden(text="local_only_mode blocks non-local profiles")
    session.profile = profile
    if not session.model_id and not model_payload and profile == default_profile and default_model_id:
        session.model_id = default_model_id
    session_budget = int(getattr(advanced_cost, "session_token_budget", 0) or 0)
    throttle_on_budget = bool(getattr(advanced_cost, "throttle_on_budget", False))
    if (
        throttle_on_budget
        and session_budget > 0
        and int(getattr(session, "session_token_spend", 0) or 0) >= session_budget
    ):
        raise web.HTTPTooManyRequests(text="Session token budget exceeded")
    model_id = payload.get("model_id")
    if isinstance(model_id, str) and model_id.strip():
        session.model_id = model_id.strip()

    companion_hints: list[str] = []
    for _key in ("channel", "source", "client", "surface"):
        _val = str(payload.get(_key) or "").strip().lower()
        if _val:
            companion_hints.append(_val)
    is_web_request = "web" in companion_hints or "web_ui" in companion_hints or "chat_ui" in companion_hints
    is_companion_chat = any(("companion" in token) or ("infinite" in token) for token in companion_hints)
    explicit_autonomy_requested = "autonomy_level" in payload
    explicit_system_prompt_requested = "system_prompt" in payload
    if "autonomy_level" in payload:
        session.autonomy_level = clamp_autonomy_level(
            payload.get("autonomy_level"),
            default=getattr(session, "autonomy_level", 3),
        )
    elif runtime_prefs is not None and not is_web_request:
        pref_level = getattr(getattr(runtime_prefs, "autonomy", None), "default_level", None)
        if pref_level:
            session.autonomy_level = parse_autonomy_level(
                pref_level,
                default=getattr(session, "autonomy_level", 3),
            )
    if "system_prompt" in payload:
        val = payload.get("system_prompt")
        session.system_prompt = val.strip() if isinstance(val, str) and val.strip() else None
    if is_companion_chat:
        if not explicit_autonomy_requested:
            # Companion phone UX should stay in guarded-auto mode by default.
            session.autonomy_level = 2
        if not explicit_system_prompt_requested and not str(getattr(session, "system_prompt", "") or "").strip():
            session.system_prompt = COMPANION_PHONE_SYSTEM_PROMPT
    if "reasoning_effort" in payload:
        val = str(payload.get("reasoning_effort") or "").strip().lower()
        if val in ("low", "medium", "high", "xhigh", ""):
            session.reasoning_effort = val or None

    if fast_mode:
        default_mode = "auto"
    else:
        default_mode = str(getattr(advanced_runtime, "default_mode", "auto") or "auto").strip().lower()
        if default_mode == "auto":
            pref_effort = str(getattr(advanced_model, "reasoning_effort", "") or "").strip().lower()
            if pref_effort in {"high", "xhigh", "max"}:
                default_mode = "thinking"
    requested_mode = str(payload.get("mode") or default_mode or "auto").strip().lower()
    default_token_economy = ""
    if not fast_mode and advanced_runtime is not None:
        default_token_economy = str(getattr(advanced_runtime, "default_token_economy", "") or "").strip().lower()
    payload_requested_token_economy = str(payload.get("token_economy") or "").strip().lower()
    requested_token_economy = str(payload_requested_token_economy or default_token_economy).strip().lower()

    from dataclasses import replace

    from thomas.core.token_economy import apply_token_economy_policy, build_token_economy_meta

    applied_token_economy, mode, run_cfg, run_max_iterations = apply_token_economy_policy(
        cfg=cfg,
        requested_level=requested_token_economy,
        requested_mode=requested_mode,
    )
    token_economy_meta = build_token_economy_meta(
        requested_level=requested_token_economy,
        applied_level=applied_token_economy,
    )
    # Attach pass limit so spawned agents (swarm workers, pipelines) can
    # pick it up.  The orchestrator itself ignores this — see
    # chat_stream_events.py for details.
    if run_max_iterations is not None:
        token_economy_meta["max_passes"] = int(run_max_iterations)
    if advanced_runtime is not None:
        run_cfg = replace(
            run_cfg,
            quality=replace(
                run_cfg.quality,
                enforce=bool(getattr(advanced_runtime, "quality_enforce", run_cfg.quality.enforce)),
                require_verification_for_coding=bool(
                    getattr(
                        advanced_runtime,
                        "quality_require_verification_for_coding",
                        run_cfg.quality.require_verification_for_coding,
                    )
                ),
                require_tests_for_code_edits=bool(
                    getattr(
                        advanced_runtime,
                        "quality_require_tests_for_code_edits",
                        run_cfg.quality.require_tests_for_code_edits,
                    )
                ),
                require_monolith_guard_for_coding=bool(
                    getattr(
                        advanced_runtime,
                        "quality_require_monolith_guard_for_coding",
                        run_cfg.quality.require_monolith_guard_for_coding,
                    )
                ),
            ),
        )
        pref_iters = int(getattr(advanced_runtime, "max_agent_iterations", 0) or 0)
        if pref_iters > 0:
            run_max_iterations = pref_iters
    if non_coder_profile:
        # Hard gate: non-coder profiles always run with strict quality enforcement.
        run_cfg = replace(
            run_cfg,
            quality=replace(
                run_cfg.quality,
                enforce=True,
                require_verification_for_coding=True,
                require_tests_for_code_edits=True,
                require_monolith_guard_for_coding=True,
            ),
        )
    if advanced_failover is not None:
        run_cfg = replace(
            run_cfg,
            failover=replace(
                run_cfg.failover,
                enabled=bool(getattr(advanced_failover, "enabled", run_cfg.failover.enabled)),
                chat_auto_failover=bool(
                    getattr(advanced_failover, "chat_auto_failover", run_cfg.failover.chat_auto_failover)
                ),
                fallback_on_auth_error=bool(
                    getattr(advanced_failover, "fallback_on_auth_error", run_cfg.failover.fallback_on_auth_error)
                ),
                cooldown_seconds=int(
                    getattr(advanced_failover, "cooldown_seconds", run_cfg.failover.cooldown_seconds) or 0
                ),
            ),
        )

    text = str(payload.get("text") or payload.get("message") or payload.get("prompt") or "")
    raw_user_text = str(text or "")
    session.last_user_message = raw_user_text
    requested_job_type = str(payload.get("job_type") or "").strip().lower() or None
    docs = payload.get("docs") or []
    images = payload.get("images") or []
    manager = _resolve_app_value(request.app, APP_ENGINE_MANAGER)
    if manager is not None:
        with contextlib.suppress(Exception):
            manager.record_user_message()
    with contextlib.suppress(Exception):
        from thomas.server.routes.autopilot import maybe_auto_start_autopilot_from_chat

        await maybe_auto_start_autopilot_from_chat(
            request,
            text=raw_user_text,
            session_id=sid,
            profile=profile,
            model_id=session.model_id,
            autonomy_level=int(getattr(session, "autonomy_level", 3) or 3),
        )

    ledger = _resolve_app_value(request.app, APP_TASK_LEDGER)
    if ledger is not None:
        try:
            from thomas.observability.task_ledger import derive_active_goal

            current_state = ledger.get_current(sid)
            next_goal = derive_active_goal(
                raw_user_text,
                current_goal=(current_state.active_goal if current_state is not None else ""),
            )
            deps.task_ledger_update(
                sid,
                active_goal=next_goal,
                status="in_progress",
                missing_inputs=[],
                last_progress="Received user request.",
                source="chat.request",
                force_event=True,
            )
        except Exception as e:
            log.debug("Task ledger pre-chat update failed: %s", e)

    # Return all setup state
    return {
        "session": session,
        "profile": profile,
        "requested_mode": requested_mode,
        "mode": mode,
        "run_cfg": run_cfg,
        "run_max_iterations": run_max_iterations,
        "raw_user_text": raw_user_text,
        "text": text,
        "docs": docs,
        "images": images,
        "requested_job_type": requested_job_type,
        "advanced_privacy": advanced_privacy,
        "advanced_runtime": advanced_runtime,
        "advanced_cost": advanced_cost,
        "advanced_tools": advanced_tools,
        "advanced_model": advanced_model,
        "advanced_failover": advanced_failover,
        "advanced_memory": advanced_memory,
        "resolved_profile_type": resolved_profile_type,
        "non_coder_profile": non_coder_profile,
        "resolved_review_depth": resolved_review_depth,
        "runtime_prefs_saved": runtime_prefs_saved,
        "applied_token_economy": applied_token_economy,
        "requested_token_economy": requested_token_economy,
        "payload_requested_token_economy": payload_requested_token_economy,
        "token_economy_meta": token_economy_meta,
        "memory_enabled_for_turn": memory_enabled_for_turn,
        "memory_retrieval_scope": memory_retrieval_scope,
        "memory_include_thread_pref": memory_include_thread_pref,
        "memory_include_global_pref": memory_include_global_pref,
        "memory_include_profile_pref": memory_include_profile_pref,
        "memory_pins_only_pref": memory_pins_only_pref,
        "memory_max_results_pref": memory_max_results_pref,
        "memory_decay_half_life_hours_pref": memory_decay_half_life_hours_pref,
        "memory_auto_compact_enabled_pref": memory_auto_compact_enabled_pref,
        "memory_auto_compact_episode_threshold_pref": memory_auto_compact_episode_threshold_pref,
        "memory_auto_compact_min_interval_hours_pref": memory_auto_compact_min_interval_hours_pref,
        "memory_auto_optimize_enabled_pref": memory_auto_optimize_enabled_pref,
        "memory_auto_optimize_waste_threshold_pref": memory_auto_optimize_waste_threshold_pref,
        "apply_usage_budget": _apply_usage_budget,
    }
