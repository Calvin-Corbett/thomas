"""
aiohttp integration for Swarm Mode.

This module is intentionally small and dependency-free. It provides:
- POST /api/chat integration handler for mode="swarm"
- POST /api/runs/{run_id}/cancel endpoint (localhost-only)

Because Thomas' internal wiring may differ per repo version, this module exposes
a couple of hooks so app.py can pass in the existing tool executor and agent
implementations without invasive refactors.

Expected integration pattern (pseudo):

from thomas.server.swarm_mode import handle_swarm_chat, handle_cancel

async def chat_handler(request):
    payload = await request.json()
    if payload.get("mode") == "swarm":
        return await handle_swarm_chat(
            request,
            payload=payload,
            user_request=payload["message"],
            run_id=run_id,
            session_id=session_id,
            subagents=subagents,     # planner/coder/tester/reviewer objects
            tool_call=tool_call,     # async (name,args) -> dict result
            tool_mutates_fs=tool_mutates_fs,  # optional (name,args)->bool
        )
    ...

app.router.add_post("/api/runs/{run_id}/cancel", handle_cancel)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, SwarmRunRegistry
from thomas.core.rules_of_road import evaluate_rules
from thomas.core.token_economy import build_token_economy_meta, normalize_token_economy_level

ToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
OnEvent = Callable[[dict[str, Any]], Awaitable[Any]]


def _normalize_usage_payload(payload: Any) -> dict[str, int]:
    """Normalize usage object/dict to {prompt_tokens, completion_tokens, total_tokens}."""
    if isinstance(payload, dict):
        prompt_raw = payload.get("prompt_tokens", 0)
        completion_raw = payload.get("completion_tokens", 0)
        total_raw = payload.get("total_tokens", 0)
    else:
        prompt_raw = getattr(payload, "prompt_tokens", 0)
        completion_raw = getattr(payload, "completion_tokens", 0)
        total_raw = getattr(payload, "total_tokens", 0)

    try:
        prompt = max(0, int(prompt_raw or 0))
    except Exception:
        prompt = 0
    try:
        completion = max(0, int(completion_raw or 0))
    except Exception:
        completion = 0
    try:
        total = max(0, int(total_raw or 0))
    except Exception:
        total = 0
    total = max(total, prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _is_probable_task_graph_json(text: str) -> bool:
    src = str(text or "").strip()
    if not src or src[0] not in "{[":
        return False
    try:
        obj = json.loads(src)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    tasks = obj.get("tasks")
    return bool("version" in obj and "goal" in obj and isinstance(tasks, list))


def _summarize_swarm_error(error_text: str) -> str:
    text = str(error_text or "").strip()
    if not text:
        return ""
    text = re.sub(r"^[A-Za-z_][\w.]*:\s*", "", text).strip()
    if "planner output is empty" in text.lower():
        return "planner returned no output"
    return text[:220]


def _safe_swarm_final_text(
    user_request: str,
    final_text: str,
    summary: Any,
    *,
    ok: bool,
    error_text: str,
) -> str:
    text = str(final_text or "").strip()
    if text and not _is_probable_task_graph_json(text):
        return text

    if not ok:
        err = _summarize_swarm_error(error_text)
        if err:
            return f"I couldn't complete the swarm run ({err}). Please retry."
        return "I couldn't complete the swarm run before a final response was produced. Please retry."

    # Casual greetings no longer get hardcoded replies — let the LLM
    # produce a natural, context-aware response.  The old "Yo. What's up?"
    # fallback sounded robotic and repetitive.

    done_count = 0
    failed_count = 0
    blocked_count = 0
    if isinstance(summary, dict):
        status_map = summary.get("status")
        if isinstance(status_map, dict):
            for raw in status_map.values():
                status = str(raw or "").strip().lower()
                if status == "done":
                    done_count += 1
                elif status == "failed":
                    failed_count += 1
                elif status == "blocked":
                    blocked_count += 1

    if done_count or failed_count or blocked_count:
        return (
            f"Swarm finished. Done: {done_count}, failed: {failed_count}, blocked: {blocked_count}. "
            "I can give a detailed breakdown or apply fixes next."
        )
    return "Swarm finished. I can summarize results or continue with the next step."


def _should_forward_agent_text(evt: dict[str, Any]) -> bool:
    task_id = str(evt.get("task_id") or "").strip().lower()
    agent_id = str(evt.get("agent_id") or evt.get("agent") or "").strip().lower()
    # Planner output is internal (task-graph JSON and routing chatter).
    if task_id == "__plan__" or agent_id == "planner":
        return False
    return True


def _extract_request_token(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Api-Token") or "").strip()


def _resolve_app_config(request: web.Request) -> Any:
    # AppConfig is stored under an AppKey("config", ...). We cannot import that key here,
    # so resolve it by name to avoid coupling this module to create_app internals.
    for key, value in request.app.items():
        if getattr(key, "name", "") == "config":
            return value
    return request.app.get("config")


def _resolve_app_memory(request: web.Request) -> Any:
    for key, value in request.app.items():
        if getattr(key, "name", "") == "memory":
            return value
    return request.app.get("memory")


def _server_access_mode(request: web.Request) -> str:
    cfg = _resolve_app_config(request)
    mode = str(getattr(getattr(cfg, "server", None), "access_mode", "local") or "local").strip().lower()
    return "remote" if mode == "remote" else "local"


def _require_remote_token(request: web.Request) -> None:
    cfg = _resolve_app_config(request)
    expected = str(getattr(getattr(cfg, "server", None), "api_token", "") or "").strip()
    if not expected:
        raise web.HTTPUnauthorized(text="server api token is not configured")
    incoming = _extract_request_token(request)
    if not incoming:
        raise web.HTTPUnauthorized(text="missing api token")
    if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
        raise web.HTTPUnauthorized(text="invalid api token")


def _is_localhost(request: web.Request) -> bool:
    # Most reliable: peername from transport
    peer = None
    try:
        peer = request.transport.get_extra_info("peername") if request.transport else None
    except Exception:
        peer = None
    if peer and isinstance(peer, (tuple, list)) and peer:
        ip = str(peer[0])
    else:
        ip = str(request.remote or "")

    # common loopback forms
    return ip in ("127.0.0.1", "::1", "localhost")


async def handle_cancel(request: web.Request) -> web.Response:
    if _server_access_mode(request) == "remote":
        _require_remote_token(request)
    elif not _is_localhost(request):
        raise web.HTTPForbidden(text="cancel endpoint is localhost-only")

    run_id = request.match_info.get("run_id", "")
    if not run_id:
        raise web.HTTPBadRequest(text="missing run_id")

    ok = await SwarmRunRegistry.cancel(run_id)
    return web.json_response({"ok": bool(ok), "run_id": run_id})


async def handle_swarm_chat(
    request: web.Request,
    *,
    payload: dict[str, Any],
    user_request: str,
    run_id: str,
    session_id: str,
    subagents: dict[str, Any],
    tool_call: ToolCall,
    tool_mutates_fs: Callable[[str, dict[str, Any]], bool] | None = None,
    on_event: OnEvent | None = None,
) -> web.StreamResponse:
    """
    NDJSON stream response for Swarm Mode. The caller supplies:
    - run_id, session_id
    - subagents dict (planner/coder/tester/reviewer)
    - tool_call callback (executes existing Thomas tools)
    """

    cfg = SwarmConfig(
        max_parallel_tasks=int(payload.get("swarm_max_parallel", 6)),
        max_parallel_per_agent=payload.get("swarm_max_parallel_per_agent", {}) or {},
        max_tasks=int(payload.get("swarm_max_tasks", 64)),
    )

    orch = SwarmOrchestrator(
        run_id=run_id,
        config=cfg,
        tool_call=tool_call,
        tool_mutates_fs=tool_mutates_fs,
    )

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            # Session id can be helpful to the client for correlation
            "X-Session-Id": session_id,
        },
    )
    await resp.prepare(request)
    quality_tool_events: list[dict[str, Any]] = []
    pending_tool_args: dict[str, dict[str, Any]] = {}
    suppress_reviewer_stream = False

    try:
        async for evt in orch.astream(user_request=user_request, subagents=subagents):
            out = dict(evt or {})
            out.setdefault("run_id", run_id)
            if str(out.get("type") or "") == "agent_tool_start":
                tcid = str(out.get("tool_call_id") or "").strip()
                args = out.get("args")
                if tcid and isinstance(args, dict):
                    pending_tool_args[tcid] = dict(args)
            if str(out.get("type") or "") == "agent_tool_result":
                tcid = str(out.get("tool_call_id") or "").strip()
                args_meta = pending_tool_args.pop(tcid, {}) if tcid else {}
                quality_tool_events.append(
                    {
                        "name": str(out.get("tool") or ""),
                        "ok": bool(out.get("ok", False)),
                        "command": str(
                            args_meta.get("command") or args_meta.get("cmd") or args_meta.get("shell") or ""
                        )[:500],
                        "path": str(args_meta.get("path") or args_meta.get("file") or args_meta.get("filename") or "")[
                            :500
                        ],
                    }
                )
            if str(out.get("type") or "") == "swarm_done":
                usage_obj = _normalize_usage_payload(out.get("run_usage") if "run_usage" in out else out.get("usage"))
                out["usage"] = usage_obj  # legacy alias for run_usage
                out.setdefault("run_usage", usage_obj)
                out.setdefault("session_usage", usage_obj)
                token_economy_meta = payload.get("token_economy_meta")
                if not isinstance(token_economy_meta, dict):
                    requested_level = str(payload.get("token_economy") or "").strip().lower()
                    token_economy_meta = build_token_economy_meta(requested_level)
                else:
                    token_economy_meta = build_token_economy_meta(
                        token_economy_meta.get("requested"),
                        token_economy_meta.get("applied"),
                    )
                applied_level = normalize_token_economy_level(token_economy_meta.get("applied"))
                cfg = _resolve_app_config(request)
                cfg_errors: list[str] = []
                cfg_unknown: list[str] = []
                if cfg is not None:
                    try:
                        validate_fn = getattr(cfg, "validate", None)
                        if callable(validate_fn):
                            cfg_errors = list(validate_fn())
                        cfg_unknown = list(getattr(cfg, "unknown_core_keys", []) or [])
                    except Exception as cfg_e:
                        cfg_errors = [f"config_audit_failed: {type(cfg_e).__name__}: {cfg_e}"]

                quality_cfg = getattr(cfg, "quality", None) if cfg is not None else None
                require_verify = bool(getattr(quality_cfg, "require_verification_for_coding", True))
                require_tests = bool(getattr(quality_cfg, "require_tests_for_code_edits", False))
                if applied_level == "cheap":
                    require_verify = True
                    require_tests = False
                elif applied_level == "max":
                    require_verify = True
                    require_tests = True
                requested_job_type = str(payload.get("job_type") or "").strip().lower() or None
                rules_report = evaluate_rules(
                    route_path="swarm_mode",
                    prompt_text=str(user_request or ""),
                    response_text=str(out.get("final") or ""),
                    tool_events=quality_tool_events,
                    requested_job_type=requested_job_type,
                    config_errors=cfg_errors,
                    unknown_core_keys=cfg_unknown,
                    require_verification_for_coding=require_verify,
                    require_tests_for_code_edits=require_tests,
                    require_monolith_guard_for_coding=bool(
                        getattr(quality_cfg, "require_monolith_guard_for_coding", True)
                    ),
                    attempt=0,
                )
                out["rules_of_road"] = rules_report
                out["token_economy"] = token_economy_meta
                token_report = out.get("token_report")
                if not isinstance(token_report, dict):
                    token_report = {}
                token_report["token_economy"] = token_economy_meta
                token_report["rules_of_road"] = rules_report
                memory = _resolve_app_memory(request)
                compaction_report = None
                if memory is not None:
                    compact_fn = getattr(memory, "auto_compact_from_token_report", None)
                    if callable(compact_fn):
                        try:
                            compaction_report = await asyncio.to_thread(
                                compact_fn,
                                thread_id=session_id,
                                token_report=token_report,
                            )
                        except Exception:
                            compaction_report = None
                if isinstance(compaction_report, dict):
                    token_report["memory_compaction"] = compaction_report
                out["token_report"] = token_report

            if on_event is not None:
                with contextlib.suppress(Exception):
                    maybe_out = await on_event(out)
                    if isinstance(maybe_out, dict):
                        out = dict(maybe_out)

            evt_type = str(out.get("type") or "")
            if evt_type == "agent_text":
                if not _should_forward_agent_text(out):
                    continue
                agent_id = str(out.get("agent_id") or out.get("agent") or "").strip().lower()
                text_chunk = str(out.get("text") or "")
                if agent_id == "reviewer":
                    probe = text_chunk.lstrip()
                    if not suppress_reviewer_stream and (
                        probe.startswith("{") or '"tasks"' in text_chunk or '"version"' in text_chunk
                    ):
                        suppress_reviewer_stream = True
                    if suppress_reviewer_stream:
                        continue

            compat_events: list[dict[str, Any]] = []
            if evt_type == "swarm_done":
                ok_raw = out.get("ok")
                ok_value = True if ok_raw is None else bool(ok_raw)
                out["final"] = _safe_swarm_final_text(
                    user_request=user_request,
                    final_text=str(out.get("final") or ""),
                    summary=out.get("summary"),
                    ok=ok_value,
                    error_text=str(out.get("error") or ""),
                )
                usage_obj = _normalize_usage_payload(out.get("run_usage") if "run_usage" in out else out.get("usage"))
                summary = out.get("summary")
                status_map = summary.get("status") if isinstance(summary, dict) else None
                iterations = len(status_map) if isinstance(status_map, dict) and status_map else 1
                try:
                    compat_seq = int(out.get("seq") or 0) + 1
                except Exception:
                    compat_seq = 0
                token_report = out.get("token_report") if isinstance(out.get("token_report"), dict) else {}
                token_economy = out.get("token_economy") if isinstance(out.get("token_economy"), dict) else {}
                rules_of_road = out.get("rules_of_road") if isinstance(out.get("rules_of_road"), dict) else {}
                compat_done = {
                    "type": "done",
                    "run_id": out.get("run_id", run_id),
                    "seq": compat_seq,
                    "iterations": int(iterations),
                    "tool_calls": 0,
                    "usage": usage_obj,
                    "run_usage": usage_obj,
                    "session_usage": usage_obj,
                    "token_report": token_report,
                    "token_economy": token_economy,
                    "rules_of_road": rules_of_road,
                    "elapsed_ms": float(out.get("duration_ms") or 0.0),
                }
                final_text = str(out.get("final") or "")
                if final_text:
                    compat_done["text"] = final_text
                    compat_done["final"] = final_text
                compat_events.append(compat_done)

            line = json.dumps(out, ensure_ascii=False) + "\n"
            await resp.write(line.encode("utf-8"))
            for compat in compat_events:
                compat_line = json.dumps(compat, ensure_ascii=False) + "\n"
                await resp.write(compat_line.encode("utf-8"))
    except (ConnectionResetError, asyncio.CancelledError, BrokenPipeError):
        orch.cancel()
    finally:
        with contextlib.suppress(Exception):
            await resp.write_eof()

    return resp


import contextlib
