"""Streaming event loop helpers for /api/chat."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from thomas.core.autonomy import autonomy_level_name
from thomas.core.events import EventType
from thomas.observability.journal import TaskJournal, journal_skip_reason
from thomas.observability.task_ledger import (
    classify_completion_state,
    derive_active_goal,
    extract_missing_inputs,
)
from thomas.server.routes.vibe_trace import (
    build_vibe_trace_event,
    tool_node_id,
    tool_node_label,
)

# Chat pipeline logger + training mode
try:
    from thomas.chat_logger import ChatEventKind, TrainingMode, chat_logger
except Exception:  # pragma: no cover â€“ graceful fallback
    chat_logger = None  # type: ignore[assignment]
    ChatEventKind = None  # type: ignore[assignment,misc]
    TrainingMode = None  # type: ignore[assignment,misc]

log = logging.getLogger(__name__)


async def stream_agent_events(
    *,
    agent: Any,
    prompt: Any,
    send: Callable[[dict[str, Any]], Awaitable[None]],
    send_timing: Callable[[str], Awaitable[None]],
    cfg: Any,
    session: Any,
    sid: str,
    raw_user_text: str,
    ledger: Any,
    deps: Any,
    run_id: str,
    model_cfg: Any,
    requested_runtime: dict[str, Any],
    failover_enabled_for_chat: bool,
    mode: str,
    advanced_tools: Any,
    requested_job_type: str | None,
    applied_token_economy: str,
    token_economy_meta: dict[str, Any],
    run_max_iterations: int | None,
    run_done: dict[str, Any],
    no_human_mode: str | None,
    require_command_approval: bool,
    llm: Any,
    memory: Any,
    start_t: float,
    apply_usage_budget: Callable[[int], Awaitable[dict[str, Any] | None]],
    normalize_usage_payload: Callable[[Any], dict[str, int]],
) -> TaskJournal | None:
    await send_timing("llm_client_ready")

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

    # --- Chat pipeline logging ---
    if chat_logger is not None:
        try:
            chat_logger.set_session(sid, run_id)
            chat_logger.log_event(
                ChatEventKind.REQUEST_IN,
                {
                    "text": str(raw_user_text)[:300],
                    "mode": mode,
                    "job_type": requested_job_type,
                    "token_economy": applied_token_economy,
                },
                session_id=sid,
                run_id=run_id,
            )
        except Exception:
            pass

    tools_policy_for_run = "auto"
    if advanced_tools is not None and float(getattr(advanced_tools, "auto_tool_threshold", 0.0) or 0.0) >= 0.9:
        tools_policy_for_run = "never"
    run_kwargs: dict[str, Any] = {
        "mode": str(mode or "auto"),
        "tools_policy": tools_policy_for_run,
        "job_type": requested_job_type,
        "token_economy": applied_token_economy,
    }
    if run_max_iterations is not None:
        run_kwargs["max_iterations"] = int(run_max_iterations)
    # NOTE: Token economy pass limits (run_max_iterations) are intentionally
    # NOT applied to the orchestrator â€” the user-facing chat must always
    # respond quickly.  Token economy iteration caps only apply to spawned
    # agents/tasks (parallel workers, coding pipelines, etc.).
    run_kwargs_effective = dict(run_kwargs)
    try:
        run_sig = inspect.signature(agent.run)
        sig_params = tuple(run_sig.parameters.values())
        supports_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params)
        if not supports_var_kwargs:
            allowed = {
                p.name
                for p in sig_params
                if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            }
            allowed.discard("self")
            allowed.discard("prompt")
            dropped = [k for k in list(run_kwargs_effective.keys()) if k not in allowed]
            for key in dropped:
                run_kwargs_effective.pop(key, None)
            if dropped:
                log.debug(
                    "AgentLoop.run compatibility: dropped unsupported kwargs: %s",
                    ", ".join(sorted(dropped)),
                )
    except Exception as sig_err:
        log.debug("AgentLoop.run signature inspection failed: %s", sig_err)

    await send_timing("agent_loop_start")
    first_token_sent = False
    tool_call_args_buf = ""
    journal: TaskJournal | None = None
    vibe_response_stream_active = False
    seen_tool_nodes: set[str] = set()

    run_result = agent.run(prompt, **run_kwargs_effective)
    if inspect.isawaitable(run_result):
        run_result = await run_result
    if not hasattr(run_result, "__aiter__"):
        raise TypeError(f"AgentLoop.run returned {type(run_result)!r}, expected async iterator")

    async for event in run_result:
        if event.type == EventType.AGENT_START:
            route_data = event.data.get("route", {})
            route_path = str((route_data or {}).get("path") or "general")
            route_conf = float((route_data or {}).get("confidence", 0) or 0)
            await send(
                {
                    "type": "route",
                    "route": route_data,
                    "mode": event.data.get("mode", "auto"),
                    "token_economy": token_economy_meta,
                    "tools_policy": event.data.get("tools_policy", "auto"),
                    "autonomy_level": int(event.data.get("autonomy_level", getattr(session, "autonomy_level", 3)) or 3),
                    "autonomy_name": str(
                        event.data.get("autonomy_name") or autonomy_level_name(getattr(session, "autonomy_level", 3))
                    ),
                    "no_human_mode": no_human_mode,
                    "require_command_approval": bool(require_command_approval),
                    "command_approval_bypassed": bool(
                        bool(require_command_approval) and str(no_human_mode or "").lower() == "allow"
                    ),
                }
            )
            route_input_source = str(event.data.get("route_input_source") or "").strip()
            route_detail = f"path={route_path} confidence={route_conf:.2f}"
            await emit_vibe("route.select", "success", detail=route_detail, kind="router")
            await emit_vibe(
                "llm.generate",
                "active",
                detail=f"mode={event.data.get('mode', 'auto')}",
                kind="model",
            )
            if ledger is not None:
                try:
                    current_state = ledger.get_current(sid)
                    next_goal = derive_active_goal(
                        raw_user_text,
                        current_goal=(current_state.active_goal if current_state is not None else ""),
                        route_input_source=route_input_source,
                    )
                    deps.task_ledger_update(
                        sid,
                        active_goal=next_goal,
                        status="in_progress",
                        missing_inputs=[],
                        last_progress=f"Route selected: {route_path}",
                        source="chat.route",
                        force_event=True,
                    )
                except Exception as exc:
                    log.debug("Task ledger route update failed: %s", exc)
            journal_reason = journal_skip_reason(prompt, route_data, enabled=cfg.journal.enabled)
            if journal_reason is None:
                try:
                    journal = TaskJournal(
                        journal_dir=cfg.journal.dir_path,
                        run_id=run_id,
                        prompt=prompt,
                        route=route_data,
                        model_info={"model": model_cfg.model, "provider": model_cfg.provider},
                    )
                except Exception as journal_err:
                    log.debug("Failed to init task journal: %s", journal_err)
            else:
                await send({"type": "journal_status", "status": "skipped", "reason": str(journal_reason or "")})

            # Log routing decision
            if chat_logger is not None:
                try:
                    chat_logger.log_event(
                        ChatEventKind.ROUTING,
                        {
                            "path": route_path,
                            "confidence": float((route_data or {}).get("confidence", 0)),
                            "reasons": list((route_data or {}).get("reasons", [])),
                            "mode": event.data.get("mode", "auto"),
                            "tools_policy": event.data.get("tools_policy", "auto"),
                        },
                        session_id=sid,
                        run_id=run_id,
                    )
                except Exception:
                    pass

            route_reasons = (route_data or {}).get("reasons", [])
            route_mode = event.data.get("mode", "auto")
            thinking_lines = ["Analyzing the request..."]
            if route_reasons:
                thinking_lines.append(
                    f"This looks like a {route_path.replace('_', ' ')} task (detected: {', '.join(str(r) for r in route_reasons)})"
                )
            else:
                thinking_lines.append(f"Routing as: {route_path.replace('_', ' ')}")
            if route_conf:
                thinking_lines.append(f"Confidence: {route_conf:.0%}")
            if route_mode and route_mode != "auto":
                thinking_lines.append(f"Using {route_mode} mode for deeper reasoning")
            thinking_lines.append("")
            await send({"type": "thinking", "text": "\n".join(thinking_lines) + "\n"})
            continue

        if event.type == EventType.THINKING:
            await send({"type": "thinking", "text": event.data.get("text", "")})
            continue

        if event.type == EventType.TEXT_DELTA:
            if not first_token_sent:
                await send_timing("first_token")
                first_token_sent = True
                if not vibe_response_stream_active:
                    await emit_vibe("response.stream", "active", detail="Streaming model output.", kind="stream")
                    vibe_response_stream_active = True
            await send({"type": "text", "text": event.data.get("text", "")})
            continue

        if event.type == EventType.AGENT_ITERATION:
            iter_num = int(event.data.get("iteration", event.iteration))
            iter_tokens = int(event.data.get("token_estimate", 0))
            await send(
                {
                    "type": "iteration",
                    "iteration": iter_num,
                    "token_estimate": iter_tokens,
                    "context_window": int(event.data.get("context_window", 0)),
                }
            )
            if iter_num > 1:
                await send({"type": "thinking", "text": f"\n--- Iteration {iter_num} ---\n"})
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.log_iteration(iter_num, iter_tokens)
            continue

        if event.type == EventType.TOOL_CALL_START:
            tool_name = event.data.get("tool_name", "")
            tool_id = tool_node_id(tool_name)
            if tool_id not in seen_tool_nodes:
                seen_tool_nodes.add(tool_id)
            await emit_vibe(
                "tool.exec",
                "active",
                detail=f"{tool_name} started",
                kind="tool",
            )
            await emit_vibe(
                tool_id,
                "active",
                label=tool_node_label(tool_name),
                detail="Tool call started.",
                kind="tool",
                parent_node_id="tool.exec",
            )
            await send(
                {
                    "type": "tool_start",
                    "id": event.data.get("tool_id", ""),
                    "name": tool_name,
                }
            )
            if tool_name:
                tool_desc = tool_name.replace(".", " -> ").replace("_", " ")
                await send({"type": "thinking", "text": f"- Calling {tool_desc}...\n"})
            continue

        if event.type == EventType.TOOL_CALL_ARGS_DELTA:
            tool_args_delta = event.data.get("delta", "")
            await send(
                {
                    "type": "tool_args",
                    "id": event.data.get("tool_id", ""),
                    "delta": tool_args_delta,
                }
            )
            tool_call_args_buf += str(tool_args_delta)
            continue

        if event.type == EventType.TOOL_RESULT:
            tool_ok = bool(event.data.get("ok", False))
            tool_ms = float(event.data.get("duration_ms", 0.0))
            tool_name = event.data.get("tool_name", "")
            tool_id = tool_node_id(tool_name)
            status = "success" if tool_ok else "error"
            await emit_vibe(
                tool_id,
                status,
                label=tool_node_label(tool_name),
                detail=f"Result in {tool_ms:.0f}ms.",
                kind="tool",
                parent_node_id="tool.exec",
            )
            await emit_vibe(
                "tool.exec",
                status,
                detail=f"{tool_name} finished in {tool_ms:.0f}ms.",
                kind="tool",
            )
            await send(
                {
                    "type": "tool_result",
                    "id": event.data.get("tool_id", ""),
                    "name": tool_name,
                    "ok": tool_ok,
                    "ms": tool_ms,
                    "result": event.data.get("result", ""),
                }
            )
            result_icon = "OK" if tool_ok else "ERR"
            result_line = f"  {result_icon} Done ({tool_ms:.0f}ms)\n"
            if tool_call_args_buf:
                try:
                    parsed = json.loads(tool_call_args_buf)
                    summary_parts = []
                    for key in ("path", "file_path", "filename", "query", "command", "url", "pattern", "content"):
                        if key in parsed:
                            value = str(parsed[key])
                            if len(value) > 120:
                                value = value[:120] + "..."
                            summary_parts.append(f"  {key}: {value}")
                    if summary_parts:
                        result_line = "\n".join(summary_parts) + "\n" + result_line
                except Exception:
                    pass
                tool_call_args_buf = ""
            await send({"type": "thinking", "text": result_line})
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.log_tool_result(tool_name, tool_ok, tool_ms)
            continue

        if event.type == EventType.AGENT_ERROR:
            err = str(event.data.get("error", "unknown error"))
            # Log error
            if chat_logger is not None:
                try:
                    chat_logger.log_event(
                        ChatEventKind.ERROR,
                        {"error": err[:300]},
                        session_id=sid,
                        run_id=run_id,
                    )
                except Exception:
                    pass
            run_done["ok"] = False
            run_done["error"] = err
            await emit_vibe("llm.generate", "error", detail=err, kind="model")
            await emit_vibe("response.done", "error", detail=err, kind="result")
            deps.task_ledger_update(
                sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(err),
                last_progress=err,
                source="chat.error",
                force_event=True,
            )
            await send({"type": "error", "error": err})
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.finalize(ok=False, iterations=0, tool_calls=0, error=err)
            continue

        if event.type == EventType.AGENT_END:
            end_msg = str(event.data.get("message", ""))
            if not end_msg:
                end_msg = str(event.data.get("reason", "Run ended before generating a response."))
            end_msg = end_msg.strip() or "Run ended before generating a response."

            if chat_logger is not None:
                try:
                    chat_logger.log_event(
                        ChatEventKind.ERROR,
                        {"error": end_msg[:300]},
                        session_id=sid,
                        run_id=run_id,
                    )
                except Exception:
                    pass

            run_done["ok"] = False
            run_done["error"] = end_msg
            await emit_vibe("llm.generate", "error", detail=end_msg, kind="model")
            await emit_vibe("response.done", "error", detail=end_msg, kind="result")
            with contextlib.suppress(Exception):
                deps.task_ledger_update(
                    sid,
                    status="blocked",
                    missing_inputs=extract_missing_inputs(end_msg),
                    last_progress=end_msg,
                    source="chat.end",
                    force_event=True,
                )
            await send({"type": "error", "error": end_msg})
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.finalize(ok=False, iterations=0, tool_calls=0, error=end_msg)
            continue

        if event.type != EventType.AGENT_DONE:
            continue

        usage_obj = normalize_usage_payload(event.data.get("usage"))
        session_usage_obj = normalize_usage_payload(getattr(llm, "session_usage", None))

        token_report = event.data.get("token_report")
        if not isinstance(token_report, dict):
            token_report = {}
        token_report["token_economy"] = dict(token_economy_meta)
        compaction_report = None
        if memory is not None:
            compact_fn = getattr(memory, "auto_compact_from_token_report", None)
            if callable(compact_fn):
                try:
                    compaction_report = await asyncio.to_thread(
                        compact_fn,
                        thread_id=sid,
                        token_report=token_report,
                    )
                except Exception as compaction_err:
                    log.debug("Token-report memory compaction hook failed: %s", compaction_err)
        if isinstance(compaction_report, dict):
            token_report["memory_compaction"] = compaction_report

        runtime_trace_fn = getattr(llm, "runtime_trace", None)
        if callable(runtime_trace_fn):
            try:
                runtime_model = runtime_trace_fn()
            except Exception:
                runtime_model = {
                    "requested": requested_runtime,
                    "active": {
                        "profile": str(getattr(llm.config, "name", "") or ""),
                        "provider": str(getattr(llm.config, "provider", "") or ""),
                        "model": str(getattr(llm.config, "model", "") or ""),
                        "base_url": str(getattr(llm.config, "base_url", "") or ""),
                    },
                    "failover_enabled": bool(failover_enabled_for_chat),
                    "failover_used": False,
                    "attempts": [],
                }
        else:
            runtime_model = {
                "requested": requested_runtime,
                "active": {
                    "profile": str(getattr(llm.config, "name", "") or ""),
                    "provider": str(getattr(llm.config, "provider", "") or ""),
                    "model": str(getattr(llm.config, "model", "") or ""),
                    "base_url": str(getattr(llm.config, "base_url", "") or ""),
                },
                "failover_enabled": bool(failover_enabled_for_chat),
                "failover_used": False,
                "attempts": [],
            }
        if not isinstance(runtime_model, dict):
            runtime_model = {
                "requested": requested_runtime,
                "active": requested_runtime,
                "failover_enabled": bool(failover_enabled_for_chat),
                "failover_used": False,
                "attempts": [],
            }
        runtime_model["strict_primary_chat"] = bool(
            not bool(runtime_model.get("failover_enabled")) and cfg.failover.enabled
        )

        done_iterations = int(event.data.get("iterations", 1))
        done_tool_calls = int(event.data.get("tool_calls", 0))
        done_total_tokens = int(usage_obj.get("total_tokens", 0) or 0)
        budget_report = await apply_usage_budget(done_total_tokens)
        if isinstance(budget_report, dict):
            token_report["budget"] = budget_report
        session_tokens_used = int((token_report.get("budget") or {}).get("session", {}).get("used_tokens", 0) or 0)
        session.session_token_spend = int(session_tokens_used)

        run_done["ok"] = True
        run_done["error"] = None
        run_done["iterations"] = done_iterations
        run_done["tool_calls"] = done_tool_calls
        run_done["usage"] = usage_obj

        assistant_text = str(event.data.get("text") or "")
        await emit_vibe(
            "llm.generate",
            "success",
            detail=f"iterations={done_iterations} tool_calls={done_tool_calls}",
            kind="model",
        )
        if done_tool_calls <= 0:
            await emit_vibe("tool.exec", "success", detail="No tools required for this turn.", kind="tool")
        if assistant_text and not vibe_response_stream_active:
            await emit_vibe("response.stream", "active", detail="Streaming finalized output.", kind="stream")
            vibe_response_stream_active = True
        await emit_vibe(
            "response.stream",
            "success",
            detail=f"{len(assistant_text)} characters delivered.",
            kind="stream",
        )
        await emit_vibe(
            "response.done",
            "success",
            detail="Response finalized.",
            kind="result",
            metadata={"iterations": done_iterations, "tool_calls": done_tool_calls},
        )

        # --- Training mode observation ---
        if TrainingMode is not None and chat_logger is not None:
            try:
                route_info = {}
                for recent in reversed(chat_logger.get_recent_events(20)):
                    if recent.kind == "routing" and recent.session_id == sid:
                        route_info = recent.data
                        break
                TrainingMode.observe_response(
                    user_text=raw_user_text,
                    assistant_text=assistant_text,
                    route_path=str(route_info.get("path", "")),
                    confidence=float(route_info.get("confidence", 0)),
                    mode=mode,
                    elapsed_ms=float((time.monotonic() - start_t) * 1000.0),
                    tool_calls=done_tool_calls,
                    session_id=sid,
                )
            except Exception as tm_err:
                log.debug("Training mode observation failed: %s", tm_err)

        # --- Log response output ---
        if chat_logger is not None:
            try:
                chat_logger.log_event(
                    ChatEventKind.RESPONSE_OUT,
                    {
                        "text_preview": assistant_text[:200],
                        "text_len": len(assistant_text),
                        "iterations": done_iterations,
                        "tool_calls": done_tool_calls,
                        "total_tokens": done_total_tokens,
                        "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
                    },
                    session_id=sid,
                    run_id=run_id,
                )
            except Exception:
                pass

        ledger_status, ledger_missing_inputs, ledger_progress = classify_completion_state(
            assistant_text=assistant_text,
            token_report=token_report,
        )
        deps.task_ledger_update(
            sid,
            status=ledger_status,
            missing_inputs=ledger_missing_inputs,
            last_progress=ledger_progress or "Turn completed.",
            source="chat.done",
            force_event=True,
        )

        if journal is not None:
            with contextlib.suppress(Exception):
                journal.finalize(
                    ok=True,
                    iterations=done_iterations,
                    tool_calls=done_tool_calls,
                    total_tokens=done_total_tokens,
                )

        await send({"type": "model_runtime", "runtime": runtime_model})
        await send(
            {
                "type": "done",
                "text": assistant_text,
                "iterations": done_iterations,
                "tool_calls": done_tool_calls,
                "usage": usage_obj,
                "run_usage": usage_obj,
                "session_usage": session_usage_obj,
                "token_report": token_report,
                "token_economy": token_economy_meta,
                "no_human_mode": no_human_mode,
                "require_command_approval": bool(require_command_approval),
                "command_approval_bypassed": bool(
                    bool(require_command_approval) and str(no_human_mode or "").lower() == "allow"
                ),
                "rules_of_road": token_report.get("rules_of_road", {}),
                "runtime_model": runtime_model,
                "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            }
        )

    return journal
