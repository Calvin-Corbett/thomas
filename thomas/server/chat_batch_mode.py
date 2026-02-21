"""Batch-mode chat orchestration for aiohttp server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import web

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchModeDeps:
    start_run_writer: Callable[[str, str], Any]
    normalize_usage_payload: Callable[[Any], Dict[str, int]]
    autonomy_level_name: Callable[[int], str]
    batch_client_factory: Any
    build_completion_request: Callable[..., Dict[str, Any]]
    parse_batch_state: Callable[[Any], Dict[str, Any]]
    extract_batch_results: Callable[[Any], List[Dict[str, Any]]]
    extract_result_request_id: Callable[[Dict[str, Any]], str]
    extract_result_error: Callable[[Dict[str, Any]], Any]
    extract_result_text: Callable[[Dict[str, Any]], Any]
    evaluate_rules: Callable[..., Dict[str, Any]]
    load_config: Callable[[Path], Any]


async def handle_batch_mode_chat(
    request: web.Request,
    *,
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
    deps: BatchModeDeps,
) -> web.StreamResponse:
    run_id = secrets.token_urlsafe(10)
    writer = deps.start_run_writer(run_id, "batch")
    run_done: Dict[str, Any] = {
        "ok": None,
        "error": None,
        "iterations": None,
        "tool_calls": None,
        "usage": None,
    }
    batch_client: Optional[Any] = None

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

    async def send(obj: Dict[str, Any]) -> None:
        async with send_lock:
            out = dict(obj)
            out.setdefault("run_id", run_id)
            if writer is not None:
                try:
                    out.setdefault("seq", int(writer.seq))
                except Exception as e:
                    log.debug("Run writer seq assignment failed (batch): %s", e)
                try:
                    writer.record(out)
                except Exception as e:
                    log.debug("Run writer record failed (batch): %s", e)
            if "seq" not in out:
                out["seq"] = _next_seq()
            line = json.dumps(out, ensure_ascii=False)
            await resp.write(line.encode("utf-8") + b"\n")

    requested_runtime = {
        "profile": str(getattr(model_cfg, "name", "") or profile or ""),
        "provider": str(getattr(model_cfg, "provider", "") or ""),
        "model": str(getattr(model_cfg, "model", "") or ""),
        "base_url": str(getattr(model_cfg, "base_url", "") or ""),
    }
    runtime_model = {
        "requested": requested_runtime,
        "active": requested_runtime,
        "failover_enabled": False,
        "failover_used": False,
        "attempts": [],
        "strict_primary_chat": bool(getattr(getattr(cfg, "failover", None), "enabled", False)),
    }

    try:
        await send({"type": "model_runtime", "runtime": runtime_model})
        await send(
            {
                "type": "route",
                "route": {"path": "batch_mode", "confidence": 1.0},
                "mode": "batch",
                "token_economy": token_economy_meta,
                "tools_policy": "never",
                "autonomy_level": int(getattr(session, "autonomy_level", 3) or 3),
                "autonomy_name": deps.autonomy_level_name(int(getattr(session, "autonomy_level", 3) or 3)),
            }
        )

        user_text = str(text or "").strip()
        if user_text:
            session.conversation.append({"role": "user", "content": user_text})

        batch_client = deps.batch_client_factory(model_cfg)
        request_id = f"req_{secrets.token_hex(8)}"
        request_payload = {
            "batch_request_id": request_id,
            "request": deps.build_completion_request(
                model_cfg=model_cfg,
                messages=[{"role": "user", "content": user_text or "(empty request)"}],
            ),
        }
        submission = await batch_client.create_and_add_chat_requests(
            batch_name=f"thomas-{run_id}",
            requests=[request_payload],
        )

        timeout_s = max(1.0, min(30.0, float(getattr(model_cfg, "timeout_s", 12.0) or 12.0)))
        poll_interval_s = 0.25
        done = False
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            batch_payload = await batch_client.get_batch(batch_id=submission.batch_id)
            state = deps.parse_batch_state(batch_payload)
            if bool(state.get("done")):
                done = True
                break
            await asyncio.sleep(poll_interval_s)

        if not done:
            raise TimeoutError(f"Batch request timed out after {timeout_s:.1f}s waiting for completion.")

        results_payload = await batch_client.list_batch_results(
            batch_id=submission.batch_id,
            limit=200,
            pagination_token="",
        )
        results = deps.extract_batch_results(results_payload)
        if not results:
            raise RuntimeError("Batch completed but returned no results.")
        selected: Optional[Dict[str, Any]] = None
        target_request_id = str(submission.request_id or request_id).strip()
        for result in results:
            if deps.extract_result_request_id(result) == target_request_id:
                selected = result
                break
        if selected is None and results:
            selected = results[0]
        selected = selected or {}

        error_text = str(deps.extract_result_error(selected) or "").strip()
        answer = str(deps.extract_result_text(selected) or "").strip()
        if not answer and error_text:
            raise RuntimeError(error_text)
        if not answer:
            answer = "Batch request completed, but no text output was returned."

        session.conversation.append({"role": "assistant", "content": answer})
        await send({"type": "text", "text": answer})

        usage_obj = deps.normalize_usage_payload({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        cfg_errors: List[str] = []
        cfg_unknown: List[str] = []
        try:
            cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
            loaded_cfg = deps.load_config(cfg_path)
            cfg_errors = loaded_cfg.validate()
            cfg_unknown = list(loaded_cfg.unknown_core_keys)
        except Exception as cfg_e:
            cfg_errors = [f"config_audit_failed: {type(cfg_e).__name__}: {cfg_e}"]

        quality_cfg = getattr(run_cfg, "quality", None)
        rules_report = deps.evaluate_rules(
            route_path="batch_mode",
            prompt_text=str(text or ""),
            response_text=answer,
            tool_events=[],
            requested_job_type=requested_job_type,
            config_errors=cfg_errors,
            unknown_core_keys=cfg_unknown,
            require_verification_for_coding=bool(getattr(quality_cfg, "require_verification_for_coding", True)),
            require_tests_for_code_edits=bool(getattr(quality_cfg, "require_tests_for_code_edits", False)),
            require_monolith_guard_for_coding=bool(
                getattr(quality_cfg, "require_monolith_guard_for_coding", True)
            ),
            attempt=0,
        )
        token_report = {
            "mode": "batch",
            "iterations": 1,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "flags": [],
            "suggestions": [],
            "token_economy": token_economy_meta,
            "rules_of_road": rules_report,
        }

        run_done["ok"] = True
        run_done["error"] = None
        run_done["iterations"] = 1
        run_done["tool_calls"] = 0
        run_done["usage"] = usage_obj

        await send(
            {
                "type": "done",
                "iterations": 1,
                "tool_calls": 0,
                "usage": usage_obj,  # legacy alias for run_usage
                "run_usage": usage_obj,
                "session_usage": usage_obj,
                "token_report": token_report,
                "token_economy": token_economy_meta,
                "rules_of_road": rules_report,
                "runtime_model": runtime_model,
                "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            }
        )
    except Exception as e:
        run_done["ok"] = False
        run_done["error"] = f"{type(e).__name__}: {e}"
        try:
            await send({"type": "error", "error": run_done["error"]})
        except Exception as send_err:
            log.debug("Failed to stream batch-mode error payload: %s", send_err)
    finally:
        if batch_client is not None:
            try:
                await batch_client.close()
            except Exception as e:
                log.debug("Batch client close failed: %s", e)
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
                log.warning("Run store finalize failed (batch): %s", e)
        if writer is not None:
            try:
                writer.close()
            except Exception as e:
                log.debug("Run writer close failed (batch): %s", e)
        try:
            await resp.write_eof()
        except Exception as eof_err:
            log.debug("Failed to close batch chat stream cleanly: %s", eof_err)
    return resp
