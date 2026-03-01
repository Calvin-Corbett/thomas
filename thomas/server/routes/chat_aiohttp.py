"""aiohttp route registration for the chat execution endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any

from aiohttp import web

from thomas import __version__ as THOMAS_VERSION
from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import clamp_autonomy_level, parse_autonomy_level
from thomas.core.config import AppConfig, load_config
from thomas.core.llm import LLMClient
from thomas.core.token_economy import (
    apply_token_economy_policy,
    build_token_economy_meta,
)
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.observability.task_ledger import (
    derive_active_goal,
    extract_missing_inputs,
)
from thomas.preferences.store import (
    PreferencesStore,
    get_db_path,
    normalize_profile_type,
    normalize_review_depth,
    profile_prefers_non_coder_mode,
)
from thomas.server.app_keys import (
    APP_ACTION_AUDIT,
    APP_CONFIG,
    APP_ENGINE_MANAGER,
    APP_GUARDED_TOOL_RUNNER,
    APP_GUARDRAILS_ENABLED,
    APP_MEMORY,
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    APP_SESSIONS,
    APP_TASK_LEDGER,
    ChatSession,
)
from thomas.server.chat_control_mode import ChatControlDeps, handle_ui_control_chat
from thomas.server.routes.chat_helpers import (
    _normalize_usage_payload,
    maybe_auto_start_autopilot_from_chat,
)
from thomas.server.routes.chat_modes import (
    maybe_handle_quick_casual_reply,
)
from thomas.server.routes.chat_stream_events import stream_agent_events
from thomas.server.routes.vibe_trace import (
    build_vibe_graph_event,
    build_vibe_trace_event,
)
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools

log = logging.getLogger(__name__)
_DEFAULT_AGENT_LOOP = AgentLoop
_DEFAULT_RESOLVE_UI_CONTROL_REQUEST = resolve_ui_control_request
_DEFAULT_HANDLE_UI_CONTROL_CHAT = handle_ui_control_chat


# Per-session message queues for mid-run interruption.
# When a session has an active run, incoming messages are pushed here
# instead of being rejected. The AgentLoop checks this queue between
# tool completions and injects the message as a new user turn.
_SESSION_MSG_QUEUES: dict[str, asyncio.Queue[str | None]] = {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on", "enabled", "enable", "ok"}


def _clone_conversation_fallback(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clone_conversation_fallback(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone_conversation_fallback(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_clone_conversation_fallback(v) for v in value)
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def _create_parallel_fork_session(
    parent_sid: str,
    sessions: dict[str, Any],
) -> tuple[str, int]:
    base_session = sessions[parent_sid]
    fork_sid = f"{parent_sid}::parallel::{secrets.token_urlsafe(4)}"
    base_len = len(base_session.conversation) if isinstance(base_session, ChatSession) else 0
    try:
        cloned_conversation = copy.deepcopy(base_session.conversation)
    except Exception as exc:
        log.warning("Parallel fork: deepcopy failed for %s, using safe fallback clone: %s", parent_sid[:12], exc)
        cloned_conversation = _clone_conversation_fallback(
            base_session.conversation if isinstance(base_session, ChatSession) else []
        )
    sessions[fork_sid] = ChatSession(
        id=fork_sid,
        conversation=cloned_conversation,
        profile=str(getattr(base_session, "profile", "")),
        model_id=getattr(base_session, "model_id", None),
        autonomy_level=clamp_autonomy_level(getattr(base_session, "autonomy_level", 3), default=3),
    )
    return fork_sid, base_len


def _appkey_identity(key: Any) -> str:
    rep = repr(key)
    match = re.match(r"^<AppKey\(([^,]+),\s*type=.*\)>$", rep)
    if match:
        name = str(match.group(1) or "")
        marker = "thomas.server.app_keys."
        idx = name.find(marker)
        if idx >= 0:
            return name[idx:]
        return name
    return str(key)


def _resolve_app_value(
    app: web.Application,
    key: Any,
    *,
    expected_type: Any = None,
    default: Any = None,
    required: bool = False,
) -> Any:
    value = app.get(key)
    if expected_type is None:
        if value is not None:
            return value
    elif isinstance(value, expected_type):
        return value

    target_identity = _appkey_identity(key)
    for existing_key, existing_value in app.items():
        if _appkey_identity(existing_key) != target_identity:
            continue
        if expected_type is not None and not isinstance(existing_value, expected_type):
            continue
        app[key] = existing_value
        return existing_value

    if required:
        raise KeyError(key)
    return default


def _resolve_runtime_config(app: web.Application) -> AppConfig:
    """Return runtime AppConfig, tolerating AppKey identity drift after restarts."""
    cfg = _resolve_app_value(app, APP_CONFIG, expected_type=AppConfig)
    if isinstance(cfg, AppConfig):
        return cfg
    for value in app.values():
        if isinstance(value, AppConfig):
            app[APP_CONFIG] = value
            return value
    cfg = load_config()
    app[APP_CONFIG] = cfg
    return cfg


COMPANION_PHONE_SYSTEM_PROMPT = (
    "You are Thomas Infinite Companion, the purpose-built mobile control agent for Thomas. "
    "Your primary job is helping the user control Thomas from their phone and ship companion apps safely.\n"
    "Treat app creation, app-store publishing, and device-targeted app push as first-class flows. "
    "When the user asks for website-style experiences, prefer websocket-backed headless web modules "
    "that run inside companion app surfaces.\n"
    "Always include setup guidance when device pairing/app setup is missing. "
    "Keep responses concise and action-oriented by default. "
    "When a request implies an action, execute safely and report progress clearly. "
    "Ask only the minimum clarifying question required when intent is ambiguous."
)


# ---------------------------------------------------------------------------
# Dependency bundle
# ---------------------------------------------------------------------------
@dataclass
class ChatRouteDeps:
    """Dependency bundle for the chat route (closures from create_app)."""

    require_api_access: Any
    read_json: Any
    session_lock_for: Any
    begin_session_run: Any
    end_session_run: Any
    task_ledger_update: Any
    model_cfg_with_secrets: Any
    failover_cfgs_with_secrets: Any
    resolve_natural_model_switch: Any
    chat_file_for: Any
    read_chat_from_disk: Any
    save_chat_to_disk: Any
    build_tools: Any


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
def register_chat_routes(
    app: web.Application,
    *,
    deps: ChatRouteDeps,
) -> None:
    async def api_chat(request: web.Request) -> web.StreamResponse:
        # This endpoint can execute tool-calling flows, including file writes.
        # Keep it access-controlled (local loopback or remote token auth).
        deps.require_api_access(request)
        start_t = time.monotonic()
        payload = await deps.read_json(request)
        sid = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not sid:
            # Compatibility mode: allow single-shot callers that do not create
            # a session up front (Claude/OpenAI-style payloads).
            sid = secrets.token_urlsafe(18)
        request_sid = sid
        session_run_guard_active = False
        forked_sid: str | None = None
        fork_parent_sid: str | None = None
        fork_base_len = 0
        start_seed_events: list[dict[str, Any]] | None = None

        if not await deps.begin_session_run(sid):
            # Session has an active run. Prefer parallel-forking instead of
            # queueing so the user can branch conversation flow immediately.
            try:
                sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
                if sid not in sessions:
                    raise web.HTTPConflict(text="session is already processing another request")
                forked_sid, fork_base_len = _create_parallel_fork_session(sid, sessions)
                sid = forked_sid
                fork_parent_sid = request_sid
            except web.HTTPException:
                raise
            except Exception as fork_err:
                msg_text = str(payload.get("text") or payload.get("message") or payload.get("prompt") or "").strip()
                q = _SESSION_MSG_QUEUES.get(request_sid)
                if q is not None and msg_text:
                    try:
                        q.put_nowait(msg_text)
                        log.info("Queued interrupt message for active session %s", request_sid[:12])
                        return web.json_response(
                            {"ok": True, "queued": True, "detail": "Message queued for active run."},
                            status=202,
                        )
                    except asyncio.QueueFull:
                        pass
                raise web.HTTPConflict(text=f"parallel chat fork failed: {fork_err}")
            start_seed_events = [
                {
                    "type": "parallel_fork",
                    "text": "Parallel chat branch started.",
                    "parent_session_id": request_sid[:12],
                    "fork_session_id": sid[:12],
                    "fork_base_len": fork_base_len,
                }
            ]
            if not await deps.begin_session_run(sid):
                _SESSION_MSG_QUEUES.pop(sid, None)
                with contextlib.suppress(Exception):
                    sessions.pop(sid, None)
                raise web.HTTPConflict(text="parallel session is already processing another request")
            session_run_guard_active = True
        else:
            session_run_guard_active = True

        try:
            return await _api_chat_inner(
                request=request,
                payload=payload,
                sid=sid,
                start_t=start_t,
                start_seed_events=start_seed_events,
            )
        except web.HTTPException:
            raise  # let aiohttp handle proper HTTP errors
        except Exception as exc:
            log.exception("[thomas] api_chat setup crashed (session=%s)", sid[:12])
            deps.task_ledger_update(
                request_sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(str(exc)),
                last_progress=f"chat setup failed: {type(exc).__name__}: {exc}",
                source="chat.setup_error",
                force_event=True,
            )
            raise web.HTTPInternalServerError(text=f"chat setup failed: {type(exc).__name__}: {exc}")
        finally:
            if session_run_guard_active:
                try:
                    await deps.end_session_run(sid)
                except Exception as guard_err:
                    log.warning("[thomas] session run guard cleanup failed: %s", guard_err)
                if fork_parent_sid is not None and forked_sid is not None:
                    try:
                        sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
                        parent_session = sessions.get(fork_parent_sid)
                        fork_session = sessions.get(forked_sid)
                        if isinstance(parent_session, ChatSession) and isinstance(fork_session, ChatSession):
                            if not isinstance(parent_session.conversation, list):
                                parent_session.conversation = []
                            if isinstance(fork_session.conversation, list):
                                merge_start = max(0, int(fork_base_len))
                                if merge_start < len(fork_session.conversation):
                                    for msg in fork_session.conversation[merge_start:]:
                                        parent_session.conversation.append(_clone_conversation_fallback(msg))
                    except Exception as merge_err:
                        log.warning("Parallel fork merge failed: %s", merge_err)
                    finally:
                        sessions.pop(forked_sid, None)

    async def _api_chat_inner(
        request: web.Request,
        payload: dict[str, Any],
        sid: str,
        start_t: float,
        start_seed_events: list[dict[str, Any]] | None = None,
    ) -> web.StreamResponse:
        session_lock = await deps.session_lock_for(sid)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        fast_mode = _as_bool(payload.get("fast_mode"))
        memory_enabled_for_turn = True
        memory_retrieval_scope = "thread"
        memory_include_global_pref: bool | None = None
        memory_include_profile_pref: bool | None = None
        # Sessions are in-memory. If the server restarts, the UI may still have a
        # stale session_id persisted locally; recover by recreating the session.
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
            sessions[sid] = ChatSession(
                id=sid,
                conversation=recovered_conversation,
                profile=cfg.default_model,
                model_id=None,
                autonomy_level=2,
            )
        session: ChatSession = sessions[sid]
        if fast_mode:
            runtime_prefs = None
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
        else:
            try:
                runtime_prefs = PreferencesStore(get_db_path()).get(user_id="default", thread_id=sid)
            except Exception:
                runtime_prefs = None
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
                memory_enabled_for_turn = bool(getattr(memory_prefs, "enabled_global", True))
            else:
                memory_enabled_for_turn = bool(thread_memory_enabled)
            memory_include_global_pref = bool(getattr(advanced_memory, "include_global_memory", True))
            memory_include_profile_pref = bool(getattr(advanced_memory, "include_profile_memory", True))

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
        profile = str(profile_payload or model_payload or session.profile).strip()
        explicit_profile_requested = bool(profile_payload or model_payload)
        if profile not in cfg.models:
            if explicit_profile_requested:
                raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
            # Graceful fallback: try session profile -> default -> first available
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
        session_budget = int(getattr(advanced_cost, "session_token_budget", 0) or 0)
        throttle_on_budget = bool(getattr(advanced_cost, "throttle_on_budget", False))
        if throttle_on_budget and session_budget > 0:
            if int(getattr(session, "session_token_spend", 0) or 0) >= session_budget:
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
        requested_token_economy = str(payload.get("token_economy") or default_token_economy).strip().lower()
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
        requested_job_type = str(payload.get("job_type") or "").strip().lower() or None
        docs = payload.get("docs") or []
        images = payload.get("images") or []
        manager = _resolve_app_value(request.app, APP_ENGINE_MANAGER)
        if manager is not None:
            with contextlib.suppress(Exception):
                manager.record_user_message()
        with contextlib.suppress(Exception):
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
        run_store_mod = _resolve_app_value(request.app, APP_RUN_STORE_MODULE)
        run_store_enabled = (
            bool(_resolve_app_value(request.app, APP_RUN_STORE_ENABLED, default=False)) and run_store_mod is not None
        )

        def _start_run_writer(run_id: str, run_mode: str):
            if not run_store_enabled:
                return None
            try:
                run_store_mod.create_run(
                    {
                        "run_id": run_id,
                        "session_id": sid,
                        "profile": str(session.profile or profile),
                        "model_id": session.model_id,
                        "mode": run_mode,
                        "autonomy_level": int(getattr(session, "autonomy_level", 3) or 3),
                        "thomas_version": THOMAS_VERSION,
                    }
                )
                writer = run_store_mod.ThreadedRunWriter(run_id)
                writer.start()
                return writer
            except Exception as e:
                log.warning("Run store start failed: %s", e)
                return None

        switch_req = await deps.resolve_natural_model_switch(text, current_profile=session.profile)
        resolve_control_req_fn = resolve_ui_control_request
        handle_ui_control_chat_fn = handle_ui_control_chat
        try:
            from thomas.server import app as server_app

            if resolve_control_req_fn is _DEFAULT_RESOLVE_UI_CONTROL_REQUEST:
                resolve_candidate = getattr(
                    server_app,
                    "resolve_ui_control_request",
                    _DEFAULT_RESOLVE_UI_CONTROL_REQUEST,
                )
                if callable(resolve_candidate):
                    resolve_control_req_fn = resolve_candidate
            if handle_ui_control_chat_fn is _DEFAULT_HANDLE_UI_CONTROL_CHAT:
                handle_candidate = getattr(
                    server_app,
                    "handle_ui_control_chat",
                    _DEFAULT_HANDLE_UI_CONTROL_CHAT,
                )
                if callable(handle_candidate):
                    handle_ui_control_chat_fn = handle_candidate
        except Exception:
            resolve_control_req_fn = resolve_ui_control_request
            handle_ui_control_chat_fn = handle_ui_control_chat

        control_req = resolve_control_req_fn(text, model_switch=switch_req)
        if control_req is not None:
            async with session_lock:
                return await handle_ui_control_chat_fn(
                    request,
                    cfg=cfg,
                    session=session,
                    payload=payload,
                    text=text,
                    profile=profile,
                    mode=mode,
                    start_t=start_t,
                    token_economy_meta=token_economy_meta,
                    switch_req=switch_req,
                    control_req=control_req,
                    run_store_enabled=run_store_enabled,
                    run_store_mod=run_store_mod,
                    start_run_writer=_start_run_writer,
                    deps=ChatControlDeps(
                        clamp_autonomy_level=clamp_autonomy_level,
                        normalize_usage_payload=_normalize_usage_payload,
                    ),
                )
        quick_reply = await maybe_handle_quick_casual_reply(
            request=request,
            session_lock=session_lock,
            session=session,
            text=text,
            mode=mode,
            token_economy_meta=token_economy_meta,
            start_t=start_t,
            sid=sid,
            deps=deps,
        )
        if quick_reply is not None:
            return quick_reply
        # Attach docs as plain text blocks.
        if isinstance(docs, list) and docs:
            blocks: list[str] = []
            for d in docs[:6]:
                if not isinstance(d, dict):
                    continue
                name = str(d.get("name") or "document")
                content = str(d.get("text") or "")
                if not content.strip():
                    continue
                # Keep attachments bounded; users can paste more if needed.
                if len(content) > 50_000:
                    content = content[:50_000] + "\n... (truncated)"
                blocks.append(f"--- {name} ---\n{content}\n--- end {name} ---")
            if blocks:
                text = (text.rstrip() + "\n\n[Attached documents]\n" + "\n\n".join(blocks)).strip()
        pinned_context = str(getattr(advanced_memory, "pinned_context", "") or "").strip()
        if pinned_context:
            text = (text.rstrip() + f"\n\n[Pinned context]\n{pinned_context}").strip()
        prompt: Any = text
        if isinstance(images, list) and images:
            img0 = images[0]
            if isinstance(img0, dict) and img0.get("data_url"):
                data_url = str(img0["data_url"])
                prompt = [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
        # Build per-request model config (allow overriding the model id without mutating global config).
        model_cfg = deps.model_cfg_with_secrets(profile)
        if session.model_id:
            model_cfg = replace(model_cfg, model=session.model_id)
        if advanced_model is not None:
            model_cfg = replace(
                model_cfg,
                temperature=float(
                    getattr(advanced_model, "temperature", model_cfg.temperature) or model_cfg.temperature
                ),
                top_p=float(getattr(advanced_model, "top_p", model_cfg.top_p) or model_cfg.top_p),
                max_tokens=int(
                    getattr(advanced_model, "max_output_tokens", model_cfg.max_tokens) or model_cfg.max_tokens
                ),
                reasoning_effort=str(
                    getattr(advanced_model, "reasoning_effort", model_cfg.reasoning_effort)
                    or model_cfg.reasoning_effort
                ),
            )
        if getattr(session, "reasoning_effort", None):
            model_cfg = replace(model_cfg, reasoning_effort=session.reasoning_effort)
        fallback_cfgs = deps.failover_cfgs_with_secrets(profile)
        if advanced_cost is not None:
            chain = [
                s.strip() for s in str(getattr(advanced_cost, "model_failover_chain", "") or "").split(",") if s.strip()
            ]
            if chain:
                cfgs: list[Any] = []
                for item in chain:
                    if item == profile:
                        continue
                    if item in cfg.models:
                        cfgs.append(deps.model_cfg_with_secrets(item))
                fallback_cfgs = cfgs
        if fast_mode:
            seeded_fallbacks = {getattr(fb, "name", "") for fb in fallback_cfgs if getattr(fb, "name", "")}
            for alt_name in cfg.models:
                if alt_name == profile or alt_name in seeded_fallbacks:
                    continue
                try:
                    fallback_cfgs.append(deps.model_cfg_with_secrets(alt_name))
                except Exception as e:
                    log.debug("Skipping fast-mode fallback profile %s: %s", alt_name, e)
        if fallback_cfgs:
            deduped_fallback_cfgs: list[Any] = []
            seen_fallback = set[str]()
            for fb_cfg in fallback_cfgs:
                fb_key = f"{getattr(fb_cfg, 'name', '')}|{getattr(fb_cfg, 'provider', '')}|{getattr(fb_cfg, 'model', '')}"
                if fb_key in seen_fallback:
                    continue
                seen_fallback.add(fb_key)
                deduped_fallback_cfgs.append(fb_cfg)
            fallback_cfgs = deduped_fallback_cfgs
        setup_elapsed = time.monotonic() - start_t
        run_id = secrets.token_urlsafe(10)
        writer = _start_run_writer(run_id, mode)
        run_done: dict[str, Any] = {
            "ok": None,
            "error": None,
            "iterations": None,
            "tool_calls": None,
            "usage": None,
        }
        chat_auto_failover = bool(getattr(run_cfg.failover, "chat_auto_failover", False))
        failover_enabled_for_chat = bool(run_cfg.failover.enabled and chat_auto_failover)
        if fast_mode and fallback_cfgs:
            # In fast mode, prefer immediate resilience over strict routing.
            # If the selected profile fails during startup/runtime, transparently
            # try configured alternatives instead of stalling the web request.
            failover_enabled_for_chat = True
        request_overrides: dict[str, Any] = {}
        if advanced_model is not None:
            request_overrides["frequency_penalty"] = float(getattr(advanced_model, "frequency_penalty", 0.0) or 0.0)
            request_overrides["presence_penalty"] = float(getattr(advanced_model, "presence_penalty", 0.0) or 0.0)
            seed_val = getattr(advanced_model, "deterministic_seed", None)
            if seed_val is not None:
                request_overrides["seed"] = int(seed_val)
            request_overrides["json_mode"] = bool(getattr(advanced_model, "json_mode", False))
            stop_csv = str(getattr(advanced_model, "stop_sequences", "") or "").strip()
            if stop_csv:
                request_overrides["stop"] = [x.strip() for x in stop_csv.splitlines() if x.strip()]
        llm_max_retries = int(getattr(advanced_cost, "max_retries", 2) or 2) + 1
        llm_backoff_s = float(getattr(advanced_cost, "retry_backoff_ms", 800) or 800) / 1000.0
        llm = LLMClient(
            model_cfg,
            fallback_configs=fallback_cfgs,
            failover_enabled=failover_enabled_for_chat,
            failover_cooldown_s=run_cfg.failover.cooldown_seconds,
            failover_on_auth_error=run_cfg.failover.fallback_on_auth_error,
            max_retries=max(1, llm_max_retries),
            base_retry_delay_s=max(0.0, llm_backoff_s),
            request_overrides=request_overrides,
        )
        config = cfg  # alias used by _build_tools below
        tools: ToolRegistry = deps.build_tools(config)
        if advanced_tools is not None:
            allow_shell = bool(getattr(advanced_tools, "allow_shell", config.tools.allow_shell))
            if allow_shell and tools.get("shell.exec") is None:
                register_shell_tools(
                    tools,
                    config.tools.sandbox_path,
                    config_timeout=int(
                        getattr(advanced_tools, "tool_timeout_s", config.tools.shell_timeout)
                        or config.tools.shell_timeout
                    ),
                    allowed=True,
                )
            if not allow_shell:
                tools.unregister("shell.exec")
            if not bool(getattr(advanced_tools, "allow_file_write", True)):
                for name in ("fs.write_file", "diff.create", "diff.apply_patch", "git.commit"):
                    tools.unregister(name)
            raw_blocked = str(getattr(advanced_tools, "blocked_commands", "") or "")
            blocked_commands = [s.strip().lower() for s in raw_blocked.split(",") if s.strip()]
            allowed_paths_value = str(getattr(advanced_tools, "allowed_paths", "") or "").strip()
            require_command_approval = bool(getattr(advanced_tools, "require_command_approval", False))

            class _PolicyWrappedTools:
                """Wraps ToolRegistry to enforce tool policies.
                Delegates everything to _base except execute() which applies
                policy checks first. Uses __getattr__ as catch-all plus explicit
                dunder methods (Python bypasses __getattr__ for data model methods).
                """

                def __init__(self, base: ToolRegistry):
                    self._base = base

                async def execute(self, name: str, args: dict[str, Any]):
                    n = str(name or "").strip().lower()
                    if n == "shell.exec":
                        if require_command_approval:
                            from thomas.tools.base import ToolResult

                            return ToolResult(ok=False, error="require_command_approval policy blocks shell.exec")
                        cmd_text = str((args or {}).get("command") or "").strip().lower()
                        for token in blocked_commands:
                            if token and token in cmd_text:
                                from thomas.tools.base import ToolResult

                                return ToolResult(ok=False, error="blocked_commands policy denied shell command")
                    if allowed_paths_value and n.startswith("fs."):
                        path_text = str((args or {}).get("path") or "").strip().replace("/", "\\").lower()
                        allowed = str(allowed_paths_value).replace("/", "\\").lower()
                        if path_text.startswith("..") or (allowed and allowed not in path_text):
                            from thomas.tools.base import ToolResult

                            return ToolResult(ok=False, error="allowed_paths policy denied filesystem access")
                    return await self._base.execute(name, args)

                # Catch-all for any method not explicitly overridden
                def __getattr__(self, name: str):
                    return getattr(self._base, name)

                # Explicit dunder delegation (Python skips __getattr__ for these)
                def __len__(self) -> int:
                    return len(self._base)

                def __contains__(self, item) -> bool:
                    return item in self._base

                def __iter__(self):
                    return iter(self._base)

                def __bool__(self) -> bool:
                    return bool(self._base)

            tools = _PolicyWrappedTools(tools)  # type: ignore[assignment]
        memory = _resolve_app_value(request.app, APP_MEMORY, required=True)
        if not memory_enabled_for_turn:
            memory = None
        guardrails_enabled = bool(_resolve_app_value(request.app, APP_GUARDRAILS_ENABLED, default=False))
        guarded_runner = _resolve_app_value(request.app, APP_GUARDED_TOOL_RUNNER) if guardrails_enabled else None
        action_audit = _resolve_app_value(request.app, APP_ACTION_AUDIT)
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )
        await resp.prepare(request)
        send_lock = asyncio.Lock()
        next_seq = {"value": 0}

        def _next_seq() -> int:
            try:
                value = int(next_seq["value"])
                if value < 0:
                    value = 0
            except Exception:
                value = 0
            next_seq["value"] = value + 1
            return value

        _stream_broken = False

        async def send(obj: dict[str, Any]) -> None:
            nonlocal _stream_broken
            if _stream_broken:
                return  # client disconnected -- silently drop
            async with send_lock:
                out = dict(obj)
                out.setdefault("run_id", run_id)
                if writer is not None:
                    try:
                        out.setdefault("seq", int(writer.seq))
                    except Exception as e:
                        log.warning("Run writer seq assignment failed: %s", e)
                    try:
                        writer.record(out)
                    except Exception as e:
                        log.warning("Run writer record failed: %s", e)
                if "seq" not in out:
                    out["seq"] = _next_seq()
                line = json.dumps(out, ensure_ascii=False)
                try:
                    await resp.write(line.encode("utf-8") + b"\n")
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as write_err:
                    _stream_broken = True
                    log.debug("Client disconnected during stream write: %s", write_err)

        async def send_timing(label: str) -> None:
            elapsed = round((time.monotonic() - start_t) * 1000)
            await send({"type": "timing", "label": label, "elapsed_ms": elapsed})

        async def emit_vibe(
            node_id: str,
            status: str,
            *,
            label: str | None = None,
            detail: str | None = None,
            kind: str | None = None,
            parent_node_id: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            await send(
                build_vibe_trace_event(
                    trace_id=run_id,
                    node_id=node_id,
                    status=status,
                    label=label,
                    detail=detail,
                    kind=kind,
                    parent_node_id=parent_node_id,
                    metadata=metadata,
                )
            )

        async def _emit_guardrails_event(evt_type: str, payload_obj: dict[str, Any]) -> None:
            await send({"type": "guardrails", "event": str(evt_type), "payload": payload_obj})

        requested_runtime = {
            "profile": str(model_cfg.name or profile or ""),
            "provider": str(model_cfg.provider or ""),
            "model": str(model_cfg.model or ""),
            "base_url": str(model_cfg.base_url or ""),
        }
        # Create per-run message queue for mid-run interruption support.
        msg_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)
        _SESSION_MSG_QUEUES[sid] = msg_queue
        agent_cls = AgentLoop
        if agent_cls is _DEFAULT_AGENT_LOOP:
            try:
                from thomas.server import app as server_app

                candidate = getattr(server_app, "AgentLoop", _DEFAULT_AGENT_LOOP)
                if candidate is not None:
                    agent_cls = candidate
            except Exception:
                agent_cls = AgentLoop
        agent_base_kwargs = {
            "system_prompt": session.system_prompt,
            "conversation": session.conversation,
            "memory": memory,
            "thread_id": sid,
            "guarded_tool_runner": guarded_runner,
            "action_audit": action_audit,
            "run_id": run_id,
            "session_id": sid,
            "guardrails_event_cb": _emit_guardrails_event if guarded_runner is not None else None,
            "autonomy_level": int(getattr(session, "autonomy_level", 3) or 3),
            "max_parallel_tools": int(getattr(advanced_tools, "max_parallel_tools", 6) or 6),
            "tool_timeout_s": int(getattr(advanced_tools, "tool_timeout_s", 120) or 120),
            "message_queue": msg_queue,
            "memory_retrieval_scope": memory_retrieval_scope,
        }
        agent_profile_kwargs = {
            "non_coder_profile": bool(non_coder_profile),
            "profile_type": str(resolved_profile_type),
            "review_depth": str(resolved_review_depth),
        }
        try:
            agent = agent_cls(
                run_cfg,
                llm,
                tools,
                **agent_base_kwargs,
                **agent_profile_kwargs,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            log.warning(
                "AgentLoop signature does not accept profile flags; continuing without them: %s",
                exc,
            )
            agent = agent_cls(
                run_cfg,
                llm,
                tools,
                **agent_base_kwargs,
            )
        setattr(agent, "_memory_include_global_pref", memory_include_global_pref)
        setattr(agent, "_memory_include_profile_pref", memory_include_profile_pref)
        journal: Any | None = None
        try:
            if start_seed_events:
                for seed_event in start_seed_events:
                    if isinstance(seed_event, dict):
                        await send(seed_event)
            await send(
                build_vibe_graph_event(
                    trace_id=run_id,
                    session_id=sid,
                    profile=str(profile or ""),
                    mode=str(mode or ""),
                    autonomy_level=int(getattr(session, "autonomy_level", 3) or 3),
                )
            )
            user_preview = " ".join(raw_user_text.split()).strip()
            if len(user_preview) > 180:
                user_preview = user_preview[:177] + "..."
            await emit_vibe(
                "user.input",
                "success",
                detail=(f"Message: {user_preview}" if user_preview else "Message received."),
                kind="user",
            )
            await emit_vibe("api.chat.request", "success", detail="POST /api/chat accepted.", kind="server")
            await emit_vibe(
                "session.resolve",
                "success",
                detail=f"profile={profile} mode={mode}",
                kind="server",
            )
            await send_timing("stream_ready")
            await send(
                {
                    "type": "model_runtime",
                    "runtime": {
                        "requested": requested_runtime,
                        "active": requested_runtime,
                        "failover_enabled": bool(failover_enabled_for_chat),
                        "failover_used": False,
                        "attempts": [],
                        "strict_primary_chat": bool(not failover_enabled_for_chat and cfg.failover.enabled),
                    },
                }
            )
            no_human_mode = "allow" if int(getattr(session, "autonomy_level", 3) or 3) >= 4 else None
            require_command_approval = bool(
                getattr(advanced_tools, "require_command_approval", False)
            )
            journal = await stream_agent_events(
                agent=agent,
                prompt=prompt,
                send=send,
                send_timing=send_timing,
                cfg=cfg,
                session=session,
                sid=sid,
                raw_user_text=raw_user_text,
                ledger=ledger,
                deps=deps,
                run_id=run_id,
                model_cfg=model_cfg,
                requested_runtime=requested_runtime,
                failover_enabled_for_chat=failover_enabled_for_chat,
                mode=mode,
                advanced_tools=advanced_tools,
                requested_job_type=requested_job_type,
                applied_token_economy=applied_token_economy,
                token_economy_meta=token_economy_meta,
                run_max_iterations=run_max_iterations,
                run_done=run_done,
                no_human_mode=no_human_mode,
                require_command_approval=require_command_approval,
                llm=llm,
                memory=memory,
                start_t=start_t,
                apply_usage_budget=_apply_usage_budget,
                normalize_usage_payload=_normalize_usage_payload,
            )
        except Exception as e:
            run_done["ok"] = False
            run_done["error"] = f"{type(e).__name__}: {e}"
            deps.task_ledger_update(
                sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(run_done["error"]),
                last_progress=run_done["error"],
                source="chat.exception",
                force_event=True,
            )
            try:
                await emit_vibe("response.done", "error", detail=run_done["error"], kind="result")
                await send({"type": "error", "error": run_done["error"]})
            except Exception as send_err:
                log.warning("Failed to stream chat error payload: %s", send_err)
        finally:
            # Safety-finalize journal if it wasn't already finalized
            if journal is not None:
                try:
                    journal.finalize(
                        ok=bool(run_done.get("ok")),
                        iterations=int(run_done.get("iterations") or 0),
                        tool_calls=int(run_done.get("tool_calls") or 0),
                        error=run_done.get("error"),
                    )
                except Exception:
                    pass
            try:
                await llm.close()
            except Exception as _llm_close_err:
                log.warning("LLM client close failed: %s", _llm_close_err)
            if run_store_enabled:
                try:
                    ok_val = bool(run_done["ok"]) if run_done["ok"] is not None else False
                    run_store_mod.finalize_run(
                        run_id,
                        ok=ok_val,
                        error=None if ok_val else str(run_done.get("error") or "run failed"),
                        iterations=run_done.get("iterations"),
                        tool_calls=run_done.get("tool_calls"),
                        usage=run_done.get("usage"),
                    )
                except Exception as e:
                    log.warning("Run store finalize failed: %s", e)
            if writer is not None:
                try:
                    writer.close()
                except Exception as e:
                    log.warning("Run writer close failed: %s", e)
            # Clean up per-session interrupt queue.
            _SESSION_MSG_QUEUES.pop(sid, None)
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.warning("Failed to close chat stream cleanly: %s", eof_err)
        return resp

    app.router.add_post("/api/chat", api_chat)
