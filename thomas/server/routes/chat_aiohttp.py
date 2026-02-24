"""aiohttp route registration for the chat execution endpoint."""
from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional
from aiohttp import web
from thomas import __version__ as THOMAS_VERSION
from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.core.token_economy import (
    apply_token_economy_policy,
    build_token_economy_meta,
)
from thomas.models.capabilities import supports as model_supports
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.server.chat_control_mode import ChatControlDeps, handle_ui_control_chat
from thomas.server.routes.chat_helpers import (
    _normalize_usage_payload,
    maybe_auto_start_autopilot_from_chat,
)
from thomas.server.routes.chat_modes import (
    maybe_handle_batch_mode,
    maybe_handle_quick_casual_reply,
    maybe_handle_swarm_mode,
)
from thomas.server.routes.chat_stream_events import stream_agent_events
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.observability.task_ledger import (
    derive_active_goal,
    extract_missing_inputs,
)
from thomas.preferences.store import PreferencesStore, get_db_path
from thomas.server.app_keys import (
    APP_CONFIG, APP_MEMORY, APP_SECRETS,
    APP_SESSIONS, APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK,
    APP_SESSION_ACTIVE_RUNS, APP_SESSION_ACTIVE_RUNS_LOCK,
    APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE,
    APP_ACTION_AUDIT,
    APP_GUARDRAILS_ENABLED, APP_GUARDED_TOOL_RUNNER, APP_GUARDRAILS_CTX,
    APP_CODEX_BRIDGE, APP_ENGINE_MANAGER, APP_TASK_LEDGER,
    ChatSession,
)
log = logging.getLogger(__name__)
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
        if not await deps.begin_session_run(sid):
            raise web.HTTPConflict(text="session is already processing another request")
        session_run_guard_active = True
        try:
            return await _api_chat_inner(request, payload, sid, start_t)
        except web.HTTPException:
            raise  # let aiohttp handle proper HTTP errors
        except Exception as exc:
            log.exception("[thomas] api_chat setup crashed (session=%s)", sid[:12])
            deps.task_ledger_update(
                sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(str(exc)),
                last_progress=f"chat setup failed: {type(exc).__name__}: {exc}",
                source="chat.setup_error",
                force_event=True,
            )
            raise web.HTTPInternalServerError(
                text=f"chat setup failed: {type(exc).__name__}: {exc}"
            )
        finally:
            if session_run_guard_active:
                try:
                    await deps.end_session_run(sid)
                except Exception as guard_err:
                    log.warning("[thomas] session run guard cleanup failed: %s", guard_err)
    async def _api_chat_inner(
        request: web.Request,
        payload: Dict[str, Any],
        sid: str,
        start_t: float,
    ) -> web.StreamResponse:
        session_run_guard_active = False  # outer wrapper handles this now
        session_lock = await deps.session_lock_for(sid)
        cfg: AppConfig = request.app[APP_CONFIG]
        # Sessions are in-memory. If the server restarts, the UI may still have a
        # stale session_id persisted locally; recover by recreating the session.
        if sid not in request.app[APP_SESSIONS]:
            # Try to recover conversation from persisted chat on disk.
            recovered_conversation: List[Dict[str, Any]] = []
            try:
                chat_path = deps.chat_file_for(sid)
                if chat_path.exists():
                    saved = deps.read_chat_from_disk(chat_path)
                    if saved and isinstance(saved.get("messages"), list):
                        for m in saved["messages"]:
                            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                                recovered_conversation.append(
                                    {"role": m["role"], "content": str(m.get("content", ""))}
                                )
                        if recovered_conversation:
                            log.info(
                                "Recovered %d messages from disk for stale session %s",
                                len(recovered_conversation), sid[:12],
                            )
            except Exception as e:
                log.debug("Session recovery from disk failed for %s: %s", sid[:12], e)
            request.app[APP_SESSIONS][sid] = ChatSession(
                id=sid, conversation=recovered_conversation,
                profile=cfg.default_model, model_id=None, autonomy_level=3,
            )
        session: ChatSession = request.app[APP_SESSIONS][sid]
        try:
            runtime_prefs = PreferencesStore(get_db_path()).get(user_id="default")
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
        async def _apply_usage_budget(used_tokens: int) -> Optional[Dict[str, Any]]:
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
        if "autonomy_level" in payload:
            session.autonomy_level = clamp_autonomy_level(
                payload.get("autonomy_level"),
                default=getattr(session, "autonomy_level", 3),
            )
        elif runtime_prefs is not None:
            pref_level = str(getattr(getattr(runtime_prefs, "autonomy", None), "default_level", "") or "").strip().upper()
            level_map = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
            if pref_level in level_map:
                session.autonomy_level = int(level_map[pref_level])
        if "system_prompt" in payload:
            val = payload.get("system_prompt")
            session.system_prompt = val.strip() if isinstance(val, str) and val.strip() else None
        if "reasoning_effort" in payload:
            val = str(payload.get("reasoning_effort") or "").strip().lower()
            if val in ("low", "medium", "high", "xhigh", ""):
                session.reasoning_effort = val or None
        default_mode = str(getattr(advanced_runtime, "default_mode", "auto") or "auto").strip().lower()
        if default_mode == "auto":
            pref_effort = str(getattr(advanced_model, "reasoning_effort", "") or "").strip().lower()
            if pref_effort in {"high", "xhigh", "max"}:
                default_mode = "thinking"
        requested_mode = str(payload.get("mode") or default_mode or "auto").strip().lower()
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
        manager = request.app.get(APP_ENGINE_MANAGER)
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
                autonomy_level=int(getattr(session, "autonomy_level", 4) or 4),
            )
        ledger = request.app.get(APP_TASK_LEDGER)
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
        run_store_mod = request.app.get(APP_RUN_STORE_MODULE)
        run_store_enabled = bool(request.app.get(APP_RUN_STORE_ENABLED)) and run_store_mod is not None
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
        control_req = resolve_ui_control_request(text, model_switch=switch_req)
        if control_req is not None:
            try:
                async with session_lock:
                    return await handle_ui_control_chat(
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
            finally:
                if session_run_guard_active:
                    await deps.end_session_run(sid)
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
            try:
                return quick_reply
            finally:
                if session_run_guard_active:
                    await deps.end_session_run(sid)
        # Attach docs as plain text blocks.
        if isinstance(docs, list) and docs:
            blocks: List[str] = []
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
                temperature=float(getattr(advanced_model, "temperature", model_cfg.temperature) or model_cfg.temperature),
                top_p=float(getattr(advanced_model, "top_p", model_cfg.top_p) or model_cfg.top_p),
                max_tokens=int(getattr(advanced_model, "max_output_tokens", model_cfg.max_tokens) or model_cfg.max_tokens),
                reasoning_effort=str(getattr(advanced_model, "reasoning_effort", model_cfg.reasoning_effort) or model_cfg.reasoning_effort),
            )
        if getattr(session, "reasoning_effort", None):
            model_cfg = replace(model_cfg, reasoning_effort=session.reasoning_effort)
        fallback_cfgs = deps.failover_cfgs_with_secrets(profile)
        if advanced_cost is not None:
            chain = [s.strip() for s in str(getattr(advanced_cost, "model_failover_chain", "") or "").split(",") if s.strip()]
            if chain:
                cfgs: List[Any] = []
                for item in chain:
                    if item == profile:
                        continue
                    if item in cfg.models:
                        cfgs.append(deps.model_cfg_with_secrets(item))
                fallback_cfgs = cfgs
        # Capability fallback: if this profile does not support batch, transparently
        # fall back to normal chat mode instead of erroring.
        if mode == "batch" and not model_supports(model_cfg, "batch"):
            mode = "auto"
        # Batch mode orchestration path.
        batch_response = await maybe_handle_batch_mode(
            request=request,
            mode=mode,
            session_lock=session_lock,
            session=session,
            text=text,
            start_t=start_t,
            profile=profile,
            cfg=cfg,
            run_cfg=run_cfg,
            model_cfg=model_cfg,
            requested_job_type=requested_job_type,
            token_economy_meta=token_economy_meta,
            run_store_enabled=run_store_enabled,
            run_store_mod=run_store_mod,
            start_run_writer=_start_run_writer,
            apply_usage_budget=_apply_usage_budget,
            sid=sid,
            deps=deps,
        )
        if batch_response is not None:
            try:
                return batch_response
            finally:
                if session_run_guard_active:
                    await deps.end_session_run(sid)
        # Swarm mode orchestration path.
        swarm_response = await maybe_handle_swarm_mode(
            request=request,
            mode=mode,
            session_lock=session_lock,
            payload=payload,
            text=text,
            sid=sid,
            cfg=cfg,
            model_cfg=model_cfg,
            fallback_cfgs=fallback_cfgs,
            advanced_tools=advanced_tools,
            applied_token_economy=applied_token_economy,
            token_economy_meta=token_economy_meta,
            run_store_enabled=run_store_enabled,
            run_store_mod=run_store_mod,
            start_run_writer=_start_run_writer,
            apply_usage_budget=_apply_usage_budget,
            deps=deps,
        )
        if swarm_response is not None:
            try:
                return swarm_response
            finally:
                if session_run_guard_active:
                    await deps.end_session_run(sid)
        setup_elapsed = time.monotonic() - start_t
        run_id = secrets.token_urlsafe(10)
        writer = _start_run_writer(run_id, mode)
        run_done: Dict[str, Any] = {
            "ok": None,
            "error": None,
            "iterations": None,
            "tool_calls": None,
            "usage": None,
        }
        chat_auto_failover = bool(getattr(run_cfg.failover, "chat_auto_failover", False))
        failover_enabled_for_chat = bool(run_cfg.failover.enabled and chat_auto_failover)
        request_overrides: Dict[str, Any] = {}
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
                    config_timeout=int(getattr(advanced_tools, "tool_timeout_s", config.tools.shell_timeout) or config.tools.shell_timeout),
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
                async def execute(self, name: str, args: Dict[str, Any]):
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
        memory = request.app[APP_MEMORY]
        guarded_runner = request.app[APP_GUARDED_TOOL_RUNNER] if request.app.get(APP_GUARDRAILS_ENABLED) else None
        action_audit = request.app.get(APP_ACTION_AUDIT)
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
        async def send(obj: Dict[str, Any]) -> None:
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
        async def _emit_guardrails_event(evt_type: str, payload_obj: Dict[str, Any]) -> None:
            await send({"type": "guardrails", "event": str(evt_type), "payload": payload_obj})
        requested_runtime = {
            "profile": str(model_cfg.name or profile or ""),
            "provider": str(model_cfg.provider or ""),
            "model": str(model_cfg.model or ""),
            "base_url": str(model_cfg.base_url or ""),
        }
        agent = AgentLoop(
            run_cfg,
            llm,
            tools,
            system_prompt=session.system_prompt,
            conversation=session.conversation,
            memory=memory,
            thread_id=sid,
            guarded_tool_runner=guarded_runner,
            action_audit=action_audit,
            run_id=run_id,
            session_id=sid,
            guardrails_event_cb=_emit_guardrails_event if guarded_runner is not None else None,
            autonomy_level=int(getattr(session, "autonomy_level", 3) or 3),
            max_parallel_tools=int(getattr(advanced_tools, "max_parallel_tools", 6) or 6),
            tool_timeout_s=int(getattr(advanced_tools, "tool_timeout_s", 120) or 120),
        )
        journal: Optional[Any] = None
        try:
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
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.warning("Failed to close chat stream cleanly: %s", eof_err)
            if session_run_guard_active:
                try:
                    await deps.end_session_run(sid)
                except Exception as e:
                    log.warning("Session run guard cleanup failed: %s", e)
        return resp
    app.router.add_post("/api/chat", api_chat)
