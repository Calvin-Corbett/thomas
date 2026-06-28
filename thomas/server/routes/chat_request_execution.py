"""Streaming and agent execution for chat requests.

This module extracts the streaming, agent loop, and response handling from
the main execute_chat_request function to keep it under 800 lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.agent.loop import AgentLoop
from thomas.agent.task_definition import (
    augment_prompt_with_task_definition,
    derive_task_definition,
    evaluate_task_result,
    should_activate_task_definition,
)
from thomas.server.app_keys import (
    APP_ACTION_AUDIT,
    APP_GUARDED_TOOL_RUNNER,
    APP_GUARDRAILS_ENABLED,
    APP_TASK_LEDGER,
    ChatSession,
)

from .chat_aiohttp_helpers import (
    _SESSION_MSG_QUEUES,
    ChatRouteDeps,
    _resolve_app_value,
)

log = logging.getLogger(__name__)

_DEFAULT_AGENT_LOOP = AgentLoop


async def execute_agent_loop(
    request: web.Request,
    response: web.StreamResponse,
    start_t: float,
    start_seed_events: list[dict[str, Any]] | None,
    sid: str,
    session: ChatSession,
    cfg: Any,
    llm: Any,
    tools: Any,
    memory: Any,
    prompt: Any,
    mode: str,
    profile: str,
    run_cfg: Any,
    run_max_iterations: int | None,
    raw_user_text: str,
    requested_job_type: str | None,
    applied_token_economy: str,
    requested_token_economy: str,
    token_economy_meta: dict[str, Any],
    advanced_tools: Any,
    advanced_memory: Any,
    resolved_profile_type: str,
    non_coder_profile: bool,
    resolved_review_depth: str,
    runtime_prefs_saved: bool,
    memory_enabled_for_turn: bool,
    memory_retrieval_scope: str,
    memory_include_thread_pref: bool | None,
    memory_include_global_pref: bool | None,
    memory_include_profile_pref: bool | None,
    memory_pins_only_pref: bool | None,
    memory_max_results_pref: int | None,
    memory_decay_half_life_hours_pref: float | None,
    memory_auto_compact_enabled_pref: bool | None,
    memory_auto_compact_episode_threshold_pref: int | None,
    memory_auto_compact_min_interval_hours_pref: float | None,
    memory_auto_optimize_enabled_pref: bool | None,
    memory_auto_optimize_waste_threshold_pref: float | None,
    apply_usage_budget: Any,
    normalize_usage_payload: Any,
    deps: ChatRouteDeps,
    run_store_enabled: bool,
    run_store_mod: Any,
    run_store_writer: Any,
    run_id: str,
) -> web.StreamResponse:
    """Execute agent loop with full streaming support."""

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
            if run_store_writer is not None:
                try:
                    out.setdefault("seq", int(run_store_writer.seq))
                except Exception as e:
                    log.warning("Run writer seq assignment failed: %s", e)
                try:
                    run_store_writer.record(out)
                except Exception as e:
                    log.warning("Run writer record failed: %s", e)
            if "seq" not in out:
                out["seq"] = _next_seq()
            line = json.dumps(out, ensure_ascii=False)
            try:
                await response.write(line.encode("utf-8") + b"\n")
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
        from thomas.server.routes.vibe import build_vibe_trace_event

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

    # Plugin hook runner: dispatches before_model/before_tool/after_tool/
    # after_response into enabled installed plugins. Observational only this
    # release (continue_on_error + strict=False; return values ignored). Cheap
    # no-op when no plugins are enabled. Kept as a closure so thomas/agent stays
    # decoupled from thomas/plugins (the agent tier must not import plugins).
    def _resolve_plugins_install_root() -> str | None:
        import os

        env_dir = os.getenv("THOMAS_PLUGINS_DIR")
        if env_dir:
            return env_dir
        home = os.getenv("THOMAS_HOME")
        if home:
            return str(Path(home).expanduser() / "plugins")
        try:
            return str(Path.home() / ".thomas" / "plugins")
        except (OSError, RuntimeError):
            return None

    async def _plugin_hook_runner(name: str, payload: dict[str, Any]) -> None:
        try:
            from thomas.plugins.p108_plugin_hook_runner_core import HookRunRequest, run_hook
            from thomas.plugins.runtime import get_enabled_plugin_instances

            plugins = get_enabled_plugin_instances(_resolve_plugins_install_root())
            if not plugins:
                return
            run_hook(
                HookRunRequest(hook=name, payload=payload, strict=False, continue_on_error=True),
                plugins=plugins,
            )
        except Exception as exc:  # REVIEWED: plugin dispatch must never break a turn
            log.debug("Plugin hook dispatch for %r failed (non-fatal): %s", name, exc)

    requested_runtime = {
        "profile": str(llm.config.name or profile or ""),
        "provider": str(llm.config.provider or ""),
        "model": str(llm.config.model or ""),
        "base_url": str(llm.config.base_url or ""),
    }

    # Per-run message queue for mid-run interruption support. REUSE one the request
    # handler may have created on-demand for a rapid follow-up that arrived before this
    # point (closes the race where the queue didn't exist yet -> 409). Generous bound
    # (was 4) plus coalescing in the handler means rapid messages are merged, not
    # rejected with an error the user sees as a failed task.
    msg_queue = _SESSION_MSG_QUEUES.get(sid)
    if msg_queue is None:
        msg_queue = asyncio.Queue(maxsize=64)
        _SESSION_MSG_QUEUES[sid] = msg_queue

    guardrails_enabled = bool(_resolve_app_value(request.app, APP_GUARDRAILS_ENABLED, default=False))
    guarded_runner = _resolve_app_value(request.app, APP_GUARDED_TOOL_RUNNER) if guardrails_enabled else None
    action_audit = _resolve_app_value(request.app, APP_ACTION_AUDIT)

    agent_cls = AgentLoop
    if agent_cls is _DEFAULT_AGENT_LOOP:
        try:
            from thomas.server.routes import chat_aiohttp as chat_route_compat

            candidate = getattr(chat_route_compat, "AgentLoop", _DEFAULT_AGENT_LOOP)
            if candidate is not None and candidate is not _DEFAULT_AGENT_LOOP:
                agent_cls = candidate
        except Exception:
            pass
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
        "hook_runner": _plugin_hook_runner,
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

    # CHATBOT-ONLY GUARDRAIL (Calvin 2026-06-15): the chat agent must NOT run
    # agentic build tools or operate in the source repo. Running the office chat as
    # a full tool-enabled AgentLoop turned "build me a game" into a coding session
    # that wrote files into Thomas's own tree (web/snake/) and streamed its repo
    # reasoning ("drift-prone", apps/site) to the user. Passing NO tools makes the
    # turn conversational, and the codex provider then auto-selects its isolated,
    # non-repo cwd (no tools -> allow_tools=False -> _no_tools_cwd). Real work goes
    # to the task manager -> a worker in an isolated workspace (separate path; the
    # Evolve self-builder is also a separate path and keeps its tools).
    chat_tools: list = []
    try:
        agent = agent_cls(
            run_cfg,
            llm,
            chat_tools,
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
            chat_tools,
            **agent_base_kwargs,
        )

    agent._memory_include_thread_pref = memory_include_thread_pref
    agent._memory_include_global_pref = memory_include_global_pref
    agent._memory_include_profile_pref = memory_include_profile_pref
    agent._memory_pins_only_pref = memory_pins_only_pref
    agent._memory_max_results_pref = memory_max_results_pref
    agent._memory_decay_half_life_hours_pref = memory_decay_half_life_hours_pref
    agent._memory_auto_compact_enabled_pref = memory_auto_compact_enabled_pref
    agent._memory_auto_compact_episode_threshold_pref = memory_auto_compact_episode_threshold_pref
    agent._memory_auto_compact_min_interval_hours_pref = memory_auto_compact_min_interval_hours_pref
    agent._memory_auto_optimize_enabled_pref = memory_auto_optimize_enabled_pref
    agent._memory_auto_optimize_waste_threshold_pref = memory_auto_optimize_waste_threshold_pref
    agent._memory_auto_optimize_min_interval_hours_pref = float(
        getattr(advanced_memory, "auto_optimize_min_interval_hours", 12.0) or 12.0
    )

    journal: Any | None = None
    run_done: dict[str, Any] = {
        "ok": None,
        "error": None,
        "iterations": None,
        "tool_calls": None,
        "usage": None,
        "text": None,
        "token_report": None,
    }

    try:
        if start_seed_events:
            for seed_event in start_seed_events:
                if isinstance(seed_event, dict):
                    await send(seed_event)

        task_definition_payload: dict[str, Any] | None = None
        if should_activate_task_definition(
            prompt_text=raw_user_text,
            applied_token_economy=requested_token_economy,
            requested_job_type=requested_job_type,
        ):
            derived_definition = derive_task_definition(raw_user_text)
            task_definition_payload = derived_definition.to_dict()
            session.task_definition = dict(task_definition_payload)
            session.task_evaluation = None
            session.task_definition_status = "defining"
            prompt = augment_prompt_with_task_definition(prompt, task_definition_payload)
            deps.task_ledger_update(
                sid,
                status="in_progress",
                missing_inputs=[],
                last_progress="Defining what a good result looks like before execution.",
                source="chat.task_definition",
                force_event=True,
            )
            await send(
                {
                    "type": "task_phase",
                    "phase": "defining",
                    "label": "Defining task",
                    "session_id": sid,
                }
            )
            await send(
                {
                    "type": "task_definition",
                    "session_id": sid,
                    "status": "ready",
                    "definition": task_definition_payload,
                }
            )
            session.task_definition_status = "executing"
            deps.task_ledger_update(
                sid,
                status="in_progress",
                missing_inputs=[],
                last_progress="Task definition ready. Executing against the defined success contract.",
                source="chat.task_execution",
                force_event=True,
            )
            await send(
                {
                    "type": "task_phase",
                    "phase": "executing",
                    "label": "Executing",
                    "session_id": sid,
                }
            )

        from thomas.server.routes.vibe import build_vibe_graph_event

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
                    "failover_enabled": False,
                    "failover_used": False,
                    "attempts": [],
                    "strict_primary_chat": bool(cfg.failover.enabled),
                },
            }
        )
        try:
            autonomy_level = int(getattr(session, "autonomy_level", 3) or 3)
        except (TypeError, ValueError):
            autonomy_level = 3
        no_human_mode = "allow" if autonomy_level >= 4 else None
        require_command_approval = bool(getattr(advanced_tools, "require_command_approval", False)) and (
            autonomy_level < 4
        )

        from thomas.server.routes.chat_stream_events import stream_agent_events

        journal = await stream_agent_events(
            agent=agent,
            prompt=prompt,
            send=send,
            send_timing=send_timing,
            cfg=cfg,
            session=session,
            sid=sid,
            raw_user_text=raw_user_text,
            ledger=_resolve_app_value(request.app, APP_TASK_LEDGER),
            deps=deps,
            run_id=run_id,
            model_cfg=llm.config,
            requested_runtime=requested_runtime,
            failover_enabled_for_chat=False,
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
            apply_usage_budget=apply_usage_budget,
            normalize_usage_payload=normalize_usage_payload,
        )
        if task_definition_payload is not None:
            session.task_definition_status = "evaluating"
            await send(
                {
                    "type": "task_phase",
                    "phase": "evaluating",
                    "label": "Evaluating result",
                    "session_id": sid,
                }
            )
            evaluation = evaluate_task_result(
                task_definition_payload,
                response_text=str(run_done.get("text") or ""),
                token_report=run_done.get("token_report") if isinstance(run_done.get("token_report"), dict) else {},
                run_ok=run_done.get("ok"),
            )
            session.task_evaluation = dict(evaluation)
            session.task_definition_status = "complete"
            if str(evaluation.get("status") or "") == "failed":
                deps.task_ledger_update(
                    sid,
                    status="blocked",
                    missing_inputs=[],
                    last_progress=str(evaluation.get("summary") or "Task evaluation failed."),
                    source="chat.task_evaluation",
                    force_event=True,
                )
            else:
                deps.task_ledger_update(
                    sid,
                    status="complete",
                    missing_inputs=[],
                    last_progress=str(evaluation.get("summary") or "Task evaluation passed."),
                    source="chat.task_evaluation",
                    force_event=True,
                )
            await send(
                {
                    "type": "task_evaluation",
                    "session_id": sid,
                    "evaluation": evaluation,
                    "task_definition_status": session.task_definition_status,
                }
            )
    except Exception as e:
        from thomas.server.routes.chat_aiohttp_streaming import extract_missing_inputs

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
            with contextlib.suppress(Exception):
                journal.finalize(
                    ok=bool(run_done.get("ok")),
                    iterations=int(run_done.get("iterations") or 0),
                    tool_calls=int(run_done.get("tool_calls") or 0),
                    error=run_done.get("error"),
                )
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
        if run_store_writer is not None:
            try:
                run_store_writer.close()
            except Exception as e:
                log.warning("Run writer close failed: %s", e)
        # Clean up per-session interrupt queue.
        _SESSION_MSG_QUEUES.pop(sid, None)
        try:
            await response.write_eof()
        except Exception as eof_err:
            log.warning("Failed to close chat stream cleanly: %s", eof_err)

    return response
