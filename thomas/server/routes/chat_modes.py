"""Mode-specific handlers for /api/chat."""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from thomas.core.autonomy import autonomy_level_name
from thomas.core.config import load_config
from thomas.core.rules_of_road import evaluate_rules
from thomas.models.batching import (
    OpenAICompatBatchClient,
    build_completion_request,
    extract_batch_results,
    extract_result_error,
    extract_result_request_id,
    extract_result_text,
    parse_batch_state,
)
from thomas.observability.task_ledger import classify_completion_state, extract_missing_inputs
from thomas.server.app_keys import APP_TOOLS
from thomas.server.chat_batch_mode import BatchModeDeps, handle_batch_mode_chat
from thomas.server.routes.chat_helpers import (
    _LLMSwarmSubagent,
    _normalize_usage_payload,
    _swarm_tool_mutates_fs,
)

log = logging.getLogger(__name__)


async def maybe_handle_quick_casual_reply(
    *,
    request: web.Request,
    session_lock: Any,
    session: Any,
    text: str,
    mode: str,
    token_economy_meta: Dict[str, Any],
    start_t: float,
    sid: str,
    deps: Any,
) -> Optional[web.StreamResponse]:
    quick_casual_reply: Optional[str] = None
    lowered_text = str(text or "").strip().lower()
    if lowered_text in {"hi", "hello", "hey"}:
        quick_casual_reply = "Hello."
    if quick_casual_reply is None:
        return None

    async with session_lock:
        session.conversation.append({"role": "user", "content": text})
        session.conversation.append({"role": "assistant", "content": quick_casual_reply})
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )
    await resp.prepare(request)
    await resp.write(json.dumps({"type": "text", "text": quick_casual_reply}).encode("utf-8") + b"\n")
    await resp.write(
        json.dumps(
            {
                "type": "done",
                "iterations": 1,
                "tool_calls": 0,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "run_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "session_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "token_report": {"mode": mode, "token_economy": token_economy_meta, "rules_of_road": {}},
                "token_economy": token_economy_meta,
                "rules_of_road": {},
                "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            }
        ).encode("utf-8")
        + b"\n"
    )
    await resp.write_eof()
    deps.task_ledger_update(
        sid,
        status="complete",
        missing_inputs=[],
        last_progress=quick_casual_reply,
        source="chat.quick_reply",
        force_event=True,
    )
    return resp


async def maybe_handle_batch_mode(
    *,
    request: web.Request,
    mode: str,
    session_lock: Any,
    session: Any,
    text: str,
    start_t: float,
    profile: str,
    cfg: Any,
    run_cfg: Any,
    model_cfg: Any,
    requested_job_type: Optional[str],
    token_economy_meta: Dict[str, Any],
    run_store_enabled: bool,
    run_store_mod: Any,
    start_run_writer: Callable[[str, str], Any],
    apply_usage_budget: Callable[[int], Awaitable[Optional[Dict[str, Any]]]],
    sid: str,
    deps: Any,
) -> Optional[web.StreamResponse]:
    if mode != "batch":
        return None

    deps.task_ledger_update(
        sid,
        status="in_progress",
        missing_inputs=[],
        last_progress="Batch mode run submitted.",
        source="chat.batch",
        force_event=True,
    )

    async def _on_batch_complete(run_done: Dict[str, Any]) -> None:
        ok_val = bool(run_done.get("ok")) if run_done.get("ok") is not None else False
        if ok_val:
            deps.task_ledger_update(
                sid,
                status="complete",
                missing_inputs=[],
                last_progress="Batch mode run completed.",
                source="chat.batch_done",
                force_event=True,
            )
            return
        err_text = str(run_done.get("error") or "Batch mode run failed.")
        deps.task_ledger_update(
            sid,
            status="blocked",
            missing_inputs=extract_missing_inputs(err_text),
            last_progress=err_text,
            source="chat.batch_error",
            force_event=True,
        )

    async with session_lock:
        response = await handle_batch_mode_chat(
            request,
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
            deps=BatchModeDeps(
                start_run_writer=start_run_writer,
                normalize_usage_payload=_normalize_usage_payload,
                autonomy_level_name=autonomy_level_name,
                batch_client_factory=OpenAICompatBatchClient,
                build_completion_request=build_completion_request,
                parse_batch_state=parse_batch_state,
                extract_batch_results=extract_batch_results,
                extract_result_request_id=extract_result_request_id,
                extract_result_error=extract_result_error,
                extract_result_text=extract_result_text,
                evaluate_rules=evaluate_rules,
                load_config=load_config,
                apply_usage_budget=apply_usage_budget,
                on_complete=_on_batch_complete,
            ),
        )
    return response


async def maybe_handle_swarm_mode(
    *,
    request: web.Request,
    mode: str,
    session_lock: Any,
    payload: Dict[str, Any],
    text: str,
    sid: str,
    cfg: Any,
    model_cfg: Any,
    fallback_cfgs: list[Any],
    advanced_tools: Any,
    applied_token_economy: str,
    token_economy_meta: Dict[str, Any],
    run_store_enabled: bool,
    run_store_mod: Any,
    start_run_writer: Callable[[str, str], Any],
    apply_usage_budget: Callable[[int], Awaitable[Optional[Dict[str, Any]]]],
    deps: Any,
) -> Optional[web.StreamResponse]:
    if mode != "swarm":
        return None

    run_id = secrets.token_urlsafe(10)
    writer = start_run_writer(run_id, "swarm")
    swarm_next_seq = {"value": 0}

    def _next_seq() -> int:
        try:
            value = int(swarm_next_seq["value"])
            if value < 0:
                value = 0
        except Exception:
            value = 0
        swarm_next_seq["value"] = value + 1
        return value

    swarm_done: Dict[str, Any] = {
        "ok": None,
        "error": None,
        "iterations": None,
        "tool_calls": None,
        "usage": None,
    }
    try:
        from thomas.server.swarm_mode import handle_swarm_chat

        async def _swarm_tool_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
            if advanced_tools is not None and str(name or "").strip().lower() == "shell.exec":
                if bool(getattr(advanced_tools, "require_command_approval", False)):
                    return {
                        "ok": False,
                        "error": "require_command_approval policy blocks shell.exec",
                        "data": {},
                        "text": "",
                    }
            result = await request.app[APP_TOOLS].execute(name, args)
            return {
                "ok": bool(result.ok),
                "error": result.error,
                "data": result.data,
                "text": result.to_content(),
            }

        async def _record_swarm_event(evt: Dict[str, Any]) -> None:
            out = dict(evt or {})
            out.setdefault("run_id", run_id)
            if writer is not None:
                try:
                    out.setdefault("seq", int(writer.seq))
                except Exception as exc:
                    log.warning("Run writer seq assignment failed: %s", exc)
                try:
                    writer.record(out)
                except Exception as exc:
                    log.warning("Run writer record failed (swarm): %s", exc)
            if "seq" not in out:
                out["seq"] = _next_seq()
            if str(out.get("type") or "") == "swarm_done":
                ok_val = bool(out.get("ok", False))
                swarm_done["ok"] = ok_val
                swarm_done["error"] = None if ok_val else str(out.get("error") or "swarm failed")
                summary = out.get("summary")
                if isinstance(summary, dict):
                    statuses = summary.get("status")
                    if isinstance(statuses, dict):
                        swarm_done["iterations"] = len(statuses)
                swarm_done["tool_calls"] = None
                swarm_done["usage"] = _normalize_usage_payload(
                    out.get("run_usage") if "run_usage" in out else out.get("usage")
                )
                budget_report = await apply_usage_budget(int((swarm_done["usage"] or {}).get("total_tokens", 0) or 0))
                if isinstance(budget_report, dict):
                    token_report = out.get("token_report")
                    if not isinstance(token_report, dict):
                        token_report = {}
                    token_report["budget"] = budget_report
                    out["token_report"] = token_report
                if ok_val:
                    token_report = out.get("token_report")
                    if not isinstance(token_report, dict):
                        token_report = {}
                    assistant_text = str(out.get("final") or "")
                    ledger_status, ledger_missing_inputs, ledger_progress = classify_completion_state(
                        assistant_text=assistant_text,
                        token_report=token_report,
                    )
                    deps.task_ledger_update(
                        sid,
                        status=ledger_status,
                        missing_inputs=ledger_missing_inputs,
                        last_progress=ledger_progress or "Swarm mode run completed.",
                        source="chat.swarm_done",
                        force_event=True,
                    )
                else:
                    err_text = str(out.get("error") or "Swarm mode run failed.")
                    deps.task_ledger_update(
                        sid,
                        status="blocked",
                        missing_inputs=extract_missing_inputs(err_text),
                        last_progress=err_text,
                        source="chat.swarm_done",
                        force_event=True,
                    )

        subagents = {
            "planner": _LLMSwarmSubagent(
                "planner",
                model_cfg,
                "You are the planner. Produce strict JSON task graphs only.",
                fallback_cfgs=fallback_cfgs,
                failover_enabled=cfg.failover.enabled,
                failover_cooldown_s=cfg.failover.cooldown_seconds,
                failover_on_auth_error=cfg.failover.fallback_on_auth_error,
            ),
            "coder": _LLMSwarmSubagent(
                "coder",
                model_cfg,
                "You are the coding executor. Produce concrete, implementation-focused output.",
                fallback_cfgs=fallback_cfgs,
                failover_enabled=cfg.failover.enabled,
                failover_cooldown_s=cfg.failover.cooldown_seconds,
                failover_on_auth_error=cfg.failover.fallback_on_auth_error,
            ),
            "tester": _LLMSwarmSubagent(
                "tester",
                model_cfg,
                "You are the validation executor. Focus on tests, checks, and regressions.",
                fallback_cfgs=fallback_cfgs,
                failover_enabled=cfg.failover.enabled,
                failover_cooldown_s=cfg.failover.cooldown_seconds,
                failover_on_auth_error=cfg.failover.fallback_on_auth_error,
            ),
            "reviewer": _LLMSwarmSubagent(
                "reviewer",
                model_cfg,
                "You are the reviewer. Summarize outcomes, risks, and next actions.",
                fallback_cfgs=fallback_cfgs,
                failover_enabled=cfg.failover.enabled,
                failover_cooldown_s=cfg.failover.cooldown_seconds,
                failover_on_auth_error=cfg.failover.fallback_on_auth_error,
            ),
        }

        swarm_request = text.strip() if isinstance(text, str) and text.strip() else "No request text provided."
        swarm_payload = dict(payload)
        swarm_payload["token_economy"] = applied_token_economy
        swarm_payload["token_economy_meta"] = dict(token_economy_meta)
        deps.task_ledger_update(
            sid,
            status="in_progress",
            missing_inputs=[],
            last_progress="Swarm run submitted.",
            source="chat.swarm",
            force_event=True,
        )
        async with session_lock:
            return await handle_swarm_chat(
                request,
                payload=swarm_payload,
                user_request=swarm_request,
                run_id=run_id,
                session_id=sid,
                subagents=subagents,
                tool_call=_swarm_tool_call,
                tool_mutates_fs=_swarm_tool_mutates_fs,
                on_event=_record_swarm_event,
            )
    except Exception as exc:
        deps.task_ledger_update(
            sid,
            status="blocked",
            missing_inputs=extract_missing_inputs(str(exc)),
            last_progress=str(exc),
            source="chat.swarm_error",
            force_event=True,
        )
        if run_store_enabled:
            try:
                run_store_mod.finalize_run(
                    run_id,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    iterations=swarm_done.get("iterations"),
                    tool_calls=swarm_done.get("tool_calls"),
                    usage=swarm_done.get("usage"),
                )
            except Exception:
                log.warning("Run store finalize failed while handling swarm error", exc_info=True)
        raise web.HTTPInternalServerError(text=f"swarm mode unavailable: {type(exc).__name__}: {exc}")
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception as exc:
                log.warning("Run writer close failed (swarm): %s", exc)
