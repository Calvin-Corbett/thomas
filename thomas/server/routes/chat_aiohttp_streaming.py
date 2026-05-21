"""Orchestrates chat request execution using helper modules."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
from dataclasses import replace
from typing import Any

from aiohttp import web

from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import AppConfig
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.server.app_keys import (
    APP_MEMORY,
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    ChatSession,
)
from thomas.server.chat_control_mode import ChatControlDeps, handle_ui_control_chat

from .chat_aiohttp_helpers import (
    ChatRouteDeps,
    _as_bool,
    _resolve_app_value,
)
from .chat_plan_mode import (
    build_plan_payload,
    draft_plan,
    execute_plan,
    normalize_conversation_mode,
    normalize_plan_action,
    refine_plan,
)
from .chat_request_setup import setup_chat_request

log = logging.getLogger(__name__)

_DEFAULT_AGENT_LOOP = AgentLoop
_DEFAULT_RESOLVE_UI_CONTROL_REQUEST = resolve_ui_control_request
_DEFAULT_HANDLE_UI_CONTROL_CHAT = handle_ui_control_chat

# Get THOMAS_VERSION from package metadata
try:
    from thomas import __version__ as THOMAS_VERSION
except ImportError:
    THOMAS_VERSION = "unknown"


async def _handle_plan_mode_request(
    *,
    request: web.Request,
    sid: str,
    session: ChatSession,
    raw_user_text: str,
    payload: dict[str, Any],
    cfg: AppConfig,
    llm: Any,
    tools: Any,
    memory: Any,
    deps: ChatRouteDeps,
) -> web.StreamResponse:
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )
    await resp.prepare(request)
    send_lock = asyncio.Lock()

    async def send(obj: dict[str, Any]) -> None:
        async with send_lock:
            await resp.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")

    async def finish_error(message: str) -> web.StreamResponse:
        deps.task_ledger_update(
            sid,
            status="blocked",
            missing_inputs=[],
            last_progress=message,
            source="chat.plan_error",
        )
        await send({"type": "error", "error": message})
        with contextlib.suppress(OSError):
            await resp.write_eof()
        return resp

    try:
        from thomas.agent.execution_plan import ExecutionPlan

        initial_plan = await draft_plan(
            text=raw_user_text,
            llm=llm,
            session_id=sid,
            send=send,
        )
        if not isinstance(initial_plan, ExecutionPlan) or not initial_plan.steps:
            return await finish_error("Failed to draft execution plan")

        await send(build_plan_payload(initial_plan))
        message = payload.get("plan_action")
        if not message:
            await resp.write_eof()
            return resp

        action = normalize_plan_action(message)
        if action == "execute":
            pass
        elif action == "refine":
            feedback = payload.get("feedback")
            if feedback:
                refined_plan = await refine_plan(
                    initial_plan,
                    feedback,
                    llm,
                    send=send,
                )
                if refined_plan:
                    initial_plan = refined_plan
                    await send(build_plan_payload(initial_plan))
        elif action == "cancel":
            await resp.write_eof()
            return resp

        await execute_plan(
            initial_plan,
            tools,
            send=send,
        )
        await resp.write_eof()
        return resp
    except Exception as e:
        return await finish_error(f"{type(e).__name__}: {e}")


def _normalize_usage_payload(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize provider-specific usage payloads to the standard
    {prompt_tokens, completion_tokens, total_tokens} contract that
    tests/test_server_done_usage_contract.py asserts on. Source data may
    arrive in Anthropic shape (input_tokens / output_tokens /
    cache_*_input_tokens) or OpenAI shape (prompt_tokens / completion_tokens /
    total_tokens). Negative values and non-numeric values are clamped to 0;
    total is recomputed when the provider's total is absent or smaller than
    prompt+completion (per test_done_usage_is_normalized_for_malformed_values).
    """
    if not usage or not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _coerce_nonneg_int(value: Any) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, v)

    # Prefer OpenAI-style if present; otherwise derive from Anthropic-style.
    prompt = _coerce_nonneg_int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = _coerce_nonneg_int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    declared_total = _coerce_nonneg_int(usage.get("total_tokens") or 0)
    # If the provider's total is missing OR less than prompt+completion (malformed),
    # use the derived sum so the invariant total >= prompt + completion holds.
    derived_total = prompt + completion
    total = declared_total if declared_total >= derived_total and declared_total > 0 else derived_total
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def extract_missing_inputs(error_text: str) -> list[str]:
    """Extract missing input references from error messages."""
    if not isinstance(error_text, str):
        return []
    # Match patterns like "Missing input: x" or "missing: foo, bar"
    patterns = [
        r"[Mm]issing\s+input[s]?:\s*([^\n]+)",
        r"[Mm]issing:\s*([^\n]+)",
    ]
    results: list[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, error_text)
        for match in matches:
            items = [item.strip() for item in str(match).split(",") if item.strip()]
            results.extend(items)
    return results


async def execute_chat_request(
    request: web.Request,
    payload: dict[str, Any],
    sid: str,
    start_t: float,
    start_seed_events: list[dict[str, Any]] | None,
    session_lock: Any,
    cfg: AppConfig,
    fast_mode: bool,
    deps: ChatRouteDeps,
) -> web.StreamResponse:
    """Execute a chat request with full streaming support.

    This function orchestrates setup and agent execution by delegating to:
    - setup_chat_request: Preference loading, session setup, model resolution
    - execute_agent_loop: Agent loop, streaming, and response handling
    """

    # ─── Phase 1: Configuration and Preferences ───────────────────────────────
    setup = await setup_chat_request(
        request=request,
        payload=payload,
        sid=sid,
        cfg=cfg,
        fast_mode=fast_mode,
        deps=deps,
    )

    session = setup["session"]
    profile = setup["profile"]
    requested_mode = str(setup.get("requested_mode") or setup["mode"] or "auto").strip().lower()
    mode = setup["mode"]
    run_cfg = setup["run_cfg"]
    run_max_iterations = setup["run_max_iterations"]
    raw_user_text = setup["raw_user_text"]
    text = setup["text"]
    docs = setup["docs"]
    images = setup["images"]
    requested_job_type = setup["requested_job_type"]
    advanced_cost = setup["advanced_cost"]
    advanced_tools = setup["advanced_tools"]
    advanced_model = setup["advanced_model"]
    advanced_memory = setup["advanced_memory"]
    resolved_profile_type = setup["resolved_profile_type"]
    non_coder_profile = setup["non_coder_profile"]
    resolved_review_depth = setup["resolved_review_depth"]
    runtime_prefs_saved = setup["runtime_prefs_saved"]
    applied_token_economy = setup["applied_token_economy"]
    payload_requested_token_economy = setup["payload_requested_token_economy"]
    token_economy_meta = setup["token_economy_meta"]
    memory_enabled_for_turn = setup["memory_enabled_for_turn"]
    memory_retrieval_scope = setup["memory_retrieval_scope"]
    memory_include_thread_pref = setup["memory_include_thread_pref"]
    memory_include_global_pref = setup["memory_include_global_pref"]
    memory_include_profile_pref = setup["memory_include_profile_pref"]
    memory_pins_only_pref = setup["memory_pins_only_pref"]
    memory_max_results_pref = setup["memory_max_results_pref"]
    memory_decay_half_life_hours_pref = setup["memory_decay_half_life_hours_pref"]
    memory_auto_compact_enabled_pref = setup["memory_auto_compact_enabled_pref"]
    memory_auto_compact_episode_threshold_pref = setup["memory_auto_compact_episode_threshold_pref"]
    memory_auto_compact_min_interval_hours_pref = setup["memory_auto_compact_min_interval_hours_pref"]
    memory_auto_optimize_enabled_pref = setup["memory_auto_optimize_enabled_pref"]
    memory_auto_optimize_waste_threshold_pref = setup["memory_auto_optimize_waste_threshold_pref"]
    apply_usage_budget = setup["apply_usage_budget"]

    # ─── Phase 2: Control routing and dispatch ───────────────────────────────
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
                run_store_enabled=bool(_resolve_app_value(request.app, APP_RUN_STORE_ENABLED, default=False)),
                run_store_mod=_resolve_app_value(request.app, APP_RUN_STORE_MODULE),
                start_run_writer=lambda run_id, run_mode: None,  # placeholder
                deps=ChatControlDeps(
                    clamp_autonomy_level=clamp_autonomy_level,
                    normalize_usage_payload=_normalize_usage_payload,
                ),
            )

    # Discord channel commands (e.g. "show discord status", "/discord recent")
    # are dispatched WITHOUT spinning up the agent loop. The handler lives in
    # discord_channels_support but was orphaned during the chat refactor —
    # match_discord_chat_command + maybe_handle_discord_chat_command existed
    # but nothing in the chat pipeline called them. Reconnect it here so
    # ``tests/test_discord_channels.py::test_local_chat_can_report_discord_status_without_agent_loop``
    # gets its expected "Discord bridge status:" reply.
    try:
        from thomas.server.routes.discord_channels_support import (
            build_discord_request_context,
            maybe_handle_discord_chat_command,
        )

        discord_request_context = build_discord_request_context(payload, sid)
        discord_response = await maybe_handle_discord_chat_command(
            request=request,
            session=session,
            sid=sid,
            text=text,
            cfg=cfg,
            token_economy_meta=token_economy_meta,
            start_t=start_t,
            request_context=discord_request_context,
        )
        if discord_response is not None:
            return discord_response
    except Exception as discord_dispatch_err:
        # Never let Discord short-circuit failures bubble up — fall through
        # to the regular chat pipeline.
        log.debug("Discord chat command dispatch skipped: %s", discord_dispatch_err)

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

    # ─── Dispatch routing ────────────────────────────────────────────────────
    try:
        from thomas.agent.chat_dispatcher import dispatch_async
        from thomas.agent.dispatch import should_dispatch
        from thomas.server.routes.task_events import watch_task

        dispatch_decision = should_dispatch(text)
        force_dispatch = _as_bool(payload.get("force_dispatch"))
        if force_dispatch and dispatch_decision.action == "dispatch":
            async with session_lock:
                if not isinstance(session.conversation, list):
                    session.conversation = []
                session.conversation.append({"role": "user", "content": text})

                dispatch_resp = web.StreamResponse(
                    status=200,
                    headers={
                        "Content-Type": "application/x-ndjson; charset=utf-8",
                        "Cache-Control": "no-cache",
                    },
                )
                await dispatch_resp.prepare(request)
                dispatch_run_id = secrets.token_urlsafe(10)

                async def dispatch_send(obj: dict[str, Any]) -> None:
                    out = dict(obj)
                    out.setdefault("run_id", dispatch_run_id)
                    line = json.dumps(out, ensure_ascii=False)
                    with contextlib.suppress(ConnectionResetError, BrokenPipeError, OSError):
                        await dispatch_resp.write(line.encode("utf-8") + b"\n")

                ack_text = "On it."
                await dispatch_send({"type": "text", "text": ack_text})
                session.conversation.append({"role": "assistant", "content": ack_text})

                dispatch_result = await dispatch_async(
                    text,
                    sid,
                    emit_event=dispatch_send,
                )

                if dispatch_result.ok:
                    await dispatch_send(
                        {
                            "type": "task_dispatched",
                            "task_id": dispatch_result.task_id,
                            "text": f"Task {dispatch_result.task_id} dispatched.",
                        }
                    )
                    asyncio.create_task(
                        watch_task(
                            dispatch_result.task_id,
                            emit_event=dispatch_send,
                        )
                    )
                else:
                    log.warning(
                        "Chat dispatch failed, falling through to inline: %s",
                        dispatch_result.error,
                    )
                    await dispatch_send(
                        {
                            "type": "status",
                            "text": "Handling directly...",
                        }
                    )

                if dispatch_result.ok:
                    await dispatch_send({"type": "done"})
                    with contextlib.suppress(Exception):
                        await dispatch_resp.write_eof()
                    return dispatch_resp

    except ImportError:
        log.debug("Dispatch modules not available, using inline agent loop")
    except Exception as dispatch_exc:
        log.warning("Dispatch routing failed, falling through to inline: %s", dispatch_exc)

    # ─── Phase 3: Request processing (docs, images, model config) ────────────
    if isinstance(docs, list) and docs:
        blocks: list[str] = []
        for d in docs[:6]:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or "document")
            content = str(d.get("text") or "")
            if not content.strip():
                continue
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
        image_parts: list[dict[str, Any]] = []
        for img in images:
            if isinstance(img, dict) and img.get("data_url"):
                image_parts.append({"type": "image_url", "image_url": {"url": str(img["data_url"])}})
        if image_parts:
            prompt = [{"type": "text", "text": text}] + image_parts

    model_cfg = deps.model_cfg_with_secrets(profile)
    if session.model_id:
        model_cfg = replace(model_cfg, model=session.model_id)
    if advanced_model is not None:
        model_cfg = replace(
            model_cfg,
            temperature=float(getattr(advanced_model, "temperature", model_cfg.temperature) or model_cfg.temperature),
            top_p=float(getattr(advanced_model, "top_p", model_cfg.top_p) or model_cfg.top_p),
            max_tokens=int(getattr(advanced_model, "max_output_tokens", model_cfg.max_tokens) or model_cfg.max_tokens),
            reasoning_effort=str(
                getattr(advanced_model, "reasoning_effort", model_cfg.reasoning_effort) or model_cfg.reasoning_effort
            ),
        )
    if getattr(session, "reasoning_effort", None):
        model_cfg = replace(model_cfg, reasoning_effort=session.reasoning_effort)

    if requested_mode == "batch":
        from thomas.server.chat_batch_mode import maybe_execute_batch_chat

        batch_response = await maybe_execute_batch_chat(
            request=request,
            sid=sid,
            session=session,
            mode=requested_mode,
            model_cfg=model_cfg,
            prompt_text=text,
            token_economy_meta=token_economy_meta,
            apply_usage_budget=apply_usage_budget,
            start_t=start_t,
            task_ledger_update=deps.task_ledger_update,
        )
        if batch_response is not None:
            return batch_response

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

    # ─── Phase 4: LLM and Tools Setup ──────────────────────────────────────
    run_id = secrets.token_urlsafe(10)
    run_store_enabled = (
        bool(_resolve_app_value(request.app, APP_RUN_STORE_ENABLED, default=False))
        and _resolve_app_value(request.app, APP_RUN_STORE_MODULE) is not None
    )

    def _start_run_writer(run_id_val: str, run_mode: str):
        run_store_mod = _resolve_app_value(request.app, APP_RUN_STORE_MODULE)
        if not run_store_enabled or run_store_mod is None:
            return None
        try:
            run_store_mod.create_run(
                {
                    "run_id": run_id_val,
                    "session_id": sid,
                    "profile": str(session.profile or profile),
                    "model_id": session.model_id,
                    "mode": run_mode,
                    "autonomy_level": int(getattr(session, "autonomy_level", 3) or 3),
                    "thomas_version": THOMAS_VERSION,
                }
            )
            writer = run_store_mod.ThreadedRunWriter(run_id_val)
            writer.start()
            return writer
        except Exception as e:
            log.warning("Run store start failed: %s", e)
            return None

    writer = _start_run_writer(run_id, mode)

    chat_auto_failover = bool(getattr(run_cfg.failover, "chat_auto_failover", False))
    failover_enabled_for_chat = bool(run_cfg.failover.enabled and chat_auto_failover)
    if fast_mode and fallback_cfgs:
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

    from thomas.core.llm import LLMClient
    from thomas.tools.registry import ToolRegistry
    from thomas.tools.shell import register_shell_tools

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

    tools: ToolRegistry = deps.build_tools(cfg)
    if advanced_tools is not None:
        if runtime_prefs_saved:
            allow_shell = bool(getattr(advanced_tools, "allow_shell", cfg.tools.allow_shell))
        else:
            allow_shell = bool(cfg.tools.allow_shell)

        if allow_shell and tools.get("shell.exec") is None:
            register_shell_tools(
                tools,
                cfg.tools.sandbox_path,
                config_timeout=int(
                    getattr(advanced_tools, "tool_timeout_s", cfg.tools.shell_timeout) or cfg.tools.shell_timeout
                ),
                allowed=True,
            )

        if not allow_shell:
            tools.unregister("shell.exec")

        if not bool(getattr(advanced_tools, "allow_file_write", True)):
            for name in ("fs.write_file", "diff.create", "diff.apply_patch", "git.commit"):
                tools.unregister(name)

        raw_blocked = str(getattr(advanced_tools, "blocked_commands", "") or "")
        blocked_commands = [
            s.strip().lower() for s in raw_blocked.replace("\r", "\n").replace("\n", ",").split(",") if s.strip()
        ]
        raw_allowed_paths = str(getattr(advanced_tools, "allowed_paths", "") or "").strip()
        allowed_paths = [
            s.strip() for s in raw_allowed_paths.replace("\r", "\n").replace("\n", ",").split(",") if s.strip()
        ]

        try:
            autonomy_level_for_policy = int(getattr(session, "autonomy_level", 3) or 3)
        except (TypeError, ValueError):
            autonomy_level_for_policy = 3

        require_command_approval = bool(getattr(advanced_tools, "require_command_approval", False)) and (
            autonomy_level_for_policy < 4
        )

        class _PolicyWrappedTools:
            """Wraps ToolRegistry to enforce tool policies."""

            def __init__(self, base: ToolRegistry):
                self._base = base

            @staticmethod
            def _canonical_policy_path(raw: Any) -> tuple[str, bool]:
                text = str(raw or "").strip()
                if not text:
                    return "", False
                normalized = text.replace("\\", "/")
                drive_match = re.match(r"^[a-zA-Z]:", normalized)
                drive = str(drive_match.group(0) or "").lower() if drive_match else ""
                if drive:
                    normalized = normalized[len(drive) :]
                is_absolute = bool(drive) or normalized.startswith("/")
                parts: list[str] = []
                for segment in normalized.split("/"):
                    seg = str(segment or "").strip()
                    if not seg or seg == ".":
                        continue
                    if seg == "..":
                        if parts and parts[-1] != "..":
                            parts.pop()
                        elif not is_absolute:
                            parts.append("..")
                        continue
                    parts.append(seg.lower())
                prefix = f"{drive}/" if drive else ("/" if is_absolute else "")
                return prefix + "/".join(parts), is_absolute

            @classmethod
            def _matches_allowed_path(cls, path_value: Any, allowlist: list[str]) -> bool:
                candidate, candidate_abs = cls._canonical_policy_path(path_value)
                if not candidate:
                    return False
                for raw_allowed in allowlist:
                    allowed, allowed_abs = cls._canonical_policy_path(raw_allowed)
                    if not allowed:
                        continue
                    if allowed_abs != candidate_abs:
                        continue
                    if candidate == allowed or candidate.startswith(f"{allowed}/"):
                        return True
                return False

            async def execute(self, name: str, args: dict[str, Any]):
                n = str(name or "").strip().lower()
                for prefix in ("functions.", "function.", "tool.", "tools.", "mcp.", "mcp__"):
                    if n.startswith(prefix):
                        n = n[len(prefix) :]
                        break
                try:
                    resolved_tool = self._base.get(str(name or ""))
                    resolved_name = str(getattr(resolved_tool, "name", "") or "").strip().lower()
                    if resolved_name:
                        n = resolved_name
                except Exception:
                    pass

                if n == "shell.exec":
                    if require_command_approval:
                        from thomas.tools.base import ToolResult

                        return ToolResult(ok=False, error="require_command_approval policy blocks shell.exec")
                    cmd_text = str((args or {}).get("command") or "").strip().lower()
                    for token in blocked_commands:
                        if token and token in cmd_text:
                            from thomas.tools.base import ToolResult

                            return ToolResult(ok=False, error="blocked_commands policy denied shell command")

                if allowed_paths and n.startswith("fs."):
                    canonical_path, _ = self._canonical_policy_path((args or {}).get("path"))
                    is_parent_escape = canonical_path == ".." or canonical_path.startswith("../")
                    is_allowed = self._matches_allowed_path((args or {}).get("path"), allowed_paths)
                    if is_parent_escape or not is_allowed:
                        from thomas.tools.base import ToolResult

                        return ToolResult(ok=False, error="allowed_paths policy denied filesystem access")

                return await self._base.execute(name, args)

            def __getattr__(self, name: str):
                return getattr(self._base, name)

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

    conversation_mode = normalize_conversation_mode(
        payload.get("conversation_mode") or getattr(session, "conversation_mode", "default")
    )
    plan_action = normalize_plan_action(payload.get("plan_action"))
    session.conversation_mode = conversation_mode

    if conversation_mode == "plan" or plan_action:
        return await _handle_plan_mode_request(
            request=request,
            sid=sid,
            session=session,
            raw_user_text=raw_user_text,
            payload=payload,
            cfg=cfg,
            llm=llm,
            tools=tools,
            memory=memory,
            deps=deps,
        )

    # ─── Phase 5: Agent execution (delegated to separate module) ─────────────
    from .chat_request_execution import execute_agent_loop

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )
    await resp.prepare(request)

    return await execute_agent_loop(
        request=request,
        response=resp,
        start_t=start_t,
        start_seed_events=start_seed_events,
        sid=sid,
        session=session,
        cfg=cfg,
        llm=llm,
        tools=tools,
        memory=memory,
        prompt=prompt,
        mode=mode,
        profile=profile,
        run_cfg=run_cfg,
        run_max_iterations=run_max_iterations,
        raw_user_text=raw_user_text,
        requested_job_type=requested_job_type,
        applied_token_economy=applied_token_economy,
        requested_token_economy=payload_requested_token_economy,
        token_economy_meta=token_economy_meta,
        advanced_tools=advanced_tools,
        advanced_memory=advanced_memory,
        resolved_profile_type=resolved_profile_type,
        non_coder_profile=non_coder_profile,
        resolved_review_depth=resolved_review_depth,
        runtime_prefs_saved=runtime_prefs_saved,
        memory_enabled_for_turn=memory_enabled_for_turn,
        memory_retrieval_scope=memory_retrieval_scope,
        memory_include_thread_pref=memory_include_thread_pref,
        memory_include_global_pref=memory_include_global_pref,
        memory_include_profile_pref=memory_include_profile_pref,
        memory_pins_only_pref=memory_pins_only_pref,
        memory_max_results_pref=memory_max_results_pref,
        memory_decay_half_life_hours_pref=memory_decay_half_life_hours_pref,
        memory_auto_compact_enabled_pref=memory_auto_compact_enabled_pref,
        memory_auto_compact_episode_threshold_pref=memory_auto_compact_episode_threshold_pref,
        memory_auto_compact_min_interval_hours_pref=memory_auto_compact_min_interval_hours_pref,
        memory_auto_optimize_enabled_pref=memory_auto_optimize_enabled_pref,
        memory_auto_optimize_waste_threshold_pref=memory_auto_optimize_waste_threshold_pref,
        apply_usage_budget=apply_usage_budget,
        normalize_usage_payload=_normalize_usage_payload,
        deps=deps,
        run_store_enabled=run_store_enabled,
        run_store_mod=_resolve_app_value(request.app, APP_RUN_STORE_MODULE),
        run_store_writer=writer,
        run_id=run_id,
    )


async def maybe_handle_quick_casual_reply(
    request: web.Request,
    session_lock: Any,
    session: ChatSession,
    text: str,
    mode: str,
    token_economy_meta: dict[str, Any],
    start_t: float,
    sid: str,
    deps: ChatRouteDeps,
) -> web.StreamResponse | None:
    """Quick reply handler (placeholder)."""
    return None
