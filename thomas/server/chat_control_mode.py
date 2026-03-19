"""UI-control chat orchestration for aiohttp server."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatControlDeps:
    clamp_autonomy_level: Callable[..., int]
    normalize_usage_payload: Callable[[Any], dict[str, int]]


def _control_confirmation(ops: list[dict[str, Any]], default_text: str) -> str:
    summaries = [str(x.get("summary") or "").strip() for x in ops if str(x.get("summary") or "").strip()]
    if summaries:
        if len(summaries) == 1:
            return f"Updated {summaries[0]}."
        return "Updated " + "; ".join(summaries) + "."
    fallback = str(default_text or "").strip()
    if fallback:
        return fallback
    return "Updated requested settings."


async def handle_ui_control_chat(
    request: web.Request,
    *,
    cfg: Any,
    session: Any,
    payload: dict[str, Any],
    text: str,
    profile: str,
    mode: str,
    start_t: float,
    token_economy_meta: dict[str, Any],
    switch_req: Any,
    control_req: Any,
    run_store_enabled: bool,
    run_store_mod: Any,
    start_run_writer: Callable[[str, str], Any],
    deps: ChatControlDeps,
) -> web.StreamResponse:
    patch: dict[str, Any] = dict(getattr(control_req, "patch", None) or {})
    ops_payload = [dict(op) for op in list(getattr(control_req, "operations", None) or [])]
    payload_settings = payload.get("settings")
    current_settings = dict(payload_settings) if isinstance(payload_settings, dict) else {}

    before_profile = str(session.profile or "").strip()
    before_model_id = str(session.model_id or "").strip()
    before_mode = str(mode or "").strip().lower()
    before_autonomy = int(getattr(session, "autonomy_level", 3) or 3)

    settings_patch = patch.get("settings")
    if settings_patch is not None:
        if isinstance(settings_patch, dict):
            clean_settings_patch = dict(settings_patch)
            if "autonomyLevel" in clean_settings_patch:
                session.autonomy_level = deps.clamp_autonomy_level(
                    clean_settings_patch.get("autonomyLevel"),
                    default=getattr(session, "autonomy_level", 3),
                )
                clean_settings_patch["autonomyLevel"] = int(session.autonomy_level)
            patch["settings"] = clean_settings_patch
        else:
            patch.pop("settings", None)

    requested_profile = str(patch.get("activeProfile") or session.profile or profile).strip()
    if requested_profile in cfg.models:
        session.profile = requested_profile
        profile = requested_profile
    elif session.profile not in cfg.models:
        session.profile = cfg.default_model
        profile = cfg.default_model
    else:
        profile = session.profile

    if "activeModelId" in patch:
        requested_model_id = str(patch.get("activeModelId") or "").strip()
        session.model_id = requested_model_id or None
        patch["activeModelId"] = str(session.model_id or "")
    if "activeProfile" in patch:
        patch["activeProfile"] = session.profile

    active_model_id = str(session.model_id or cfg.models[profile].model or "").strip()
    if not active_model_id:
        active_model_id = str(cfg.models[profile].model or "")

    mode_for_run = str(patch.get("mode") or mode).strip().lower()
    if mode_for_run not in ("auto", "fast", "thinking"):
        mode_for_run = mode

    enriched_ops_payload: list[dict[str, Any]] = []
    applied_ops_payload: list[dict[str, Any]] = []
    applied_patch: dict[str, Any] = {}
    control_confidence = 0.0

    for op in ops_payload:
        op_item = dict(op)
        key = str(op_item.get("key") or "").strip()
        kind = str(op_item.get("kind") or "").strip().lower()
        confidence_raw = op_item.get("confidence", 0.0)
        try:
            op_conf = float(confidence_raw or 0.0)
        except Exception:
            op_conf = 0.0
        control_confidence = max(control_confidence, op_conf)
        op_item["confidence"] = op_conf

        applied = False
        applied_source = "client"
        before_value: Any = None
        after_value: Any = None

        if kind == "model" or key == "model":
            applied_source = "server"
            before_value = {
                "profile": before_profile,
                "model_id": before_model_id,
            }
            after_value = {
                "profile": str(profile or "").strip(),
                "model_id": str(session.model_id or "").strip(),
            }
            applied = before_value != after_value
            if applied:
                applied_patch["activeProfile"] = after_value["profile"]
                applied_patch["activeModelId"] = after_value["model_id"]
        elif key == "mode":
            applied_source = "client"
            after_value = str(patch.get("mode") or mode_for_run).strip().lower()
            before_value = before_mode
            applied = bool(after_value) and after_value != before_value
            if applied:
                applied_patch["mode"] = after_value
        elif key == "autonomyLevel":
            applied_source = "server"
            before_value = int(before_autonomy)
            after_value = int(getattr(session, "autonomy_level", 3) or 3)
            applied = after_value != before_value
            if applied:
                settings_applied = applied_patch.get("settings")
                if not isinstance(settings_applied, dict):
                    settings_applied = {}
                    applied_patch["settings"] = settings_applied
                settings_applied["autonomyLevel"] = after_value
        elif key:
            applied_source = "client"
            settings_after = patch.get("settings")
            if isinstance(settings_after, dict) and key in settings_after:
                before_value = current_settings.get(key)
                after_value = settings_after.get(key)
                applied = before_value != after_value
                if applied:
                    settings_applied = applied_patch.get("settings")
                    if not isinstance(settings_applied, dict):
                        settings_applied = {}
                        applied_patch["settings"] = settings_applied
                    settings_applied[key] = after_value

        op_item["applied"] = bool(applied)
        op_item["applied_source"] = applied_source
        op_item["before"] = before_value
        op_item["after"] = after_value
        enriched_ops_payload.append(op_item)
        if applied:
            applied_ops_payload.append(dict(op_item))

    if ops_payload:
        ops_payload = enriched_ops_payload

    if applied_ops_payload:
        confirm_text = _control_confirmation(applied_ops_payload, str(getattr(control_req, "confirmation", "") or ""))
    else:
        confirm_text = "No configuration changes were applied (already set)."

    control_meta = {
        "actor": "control_parser",
        "intent_type": "ui_control",
        "confidence": float(control_confidence),
        "operations_total": int(len(ops_payload)),
        "operations_applied": int(len(applied_ops_payload)),
        "no_op": bool(len(applied_ops_payload) == 0),
        "applied_patch": applied_patch,
    }

    model_changed = bool("activeProfile" in patch or "activeModelId" in patch)
    runtime_model: dict[str, Any] | None = None
    if model_changed:
        chat_auto_failover = bool(getattr(cfg.failover, "chat_auto_failover", False))
        failover_enabled_for_chat = bool(cfg.failover.enabled and chat_auto_failover)
        runtime_model = {
            "requested": {
                "profile": profile,
                "provider": str(cfg.models[profile].provider or ""),
                "model": active_model_id,
                "base_url": str(cfg.models[profile].base_url or ""),
            },
            "active": {
                "profile": profile,
                "provider": str(cfg.models[profile].provider or ""),
                "model": active_model_id,
                "base_url": str(cfg.models[profile].base_url or ""),
            },
            "failover_enabled": bool(failover_enabled_for_chat),
            "failover_used": False,
            "attempts": [],
            "strict_primary_chat": bool(not failover_enabled_for_chat and cfg.failover.enabled),
        }

    run_id = secrets.token_urlsafe(10)
    writer = start_run_writer(run_id, mode_for_run)

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

    async def send(obj: dict[str, Any]) -> None:
        async with send_lock:
            out = dict(obj)
            out.setdefault("run_id", run_id)
            if writer is not None:
                try:
                    out.setdefault("seq", int(writer.seq))
                except Exception as e:
                    log.debug("Run writer seq assignment failed: %s", e)
                try:
                    writer.record(out)
                except Exception as e:
                    log.debug("Run writer record failed: %s", e)
            if "seq" not in out:
                out["seq"] = _next_seq()
            line = json.dumps(out, ensure_ascii=False)
            await resp.write(line.encode("utf-8") + b"\n")

    try:
        text_clean = str(text or "").strip()
        if text_clean:
            session.conversation.append({"role": "user", "content": text_clean})
        session.conversation.append({"role": "assistant", "content": confirm_text})

        if switch_req is not None:
            await send(
                {
                    "type": "model_switch",
                    "profile": profile,
                    "model_id": str(session.model_id or ""),
                    "active_model": active_model_id,
                    "source": "conversation",
                    "confidence": float(getattr(switch_req, "confidence", 0.0) or 0.0),
                    "explanation": str(getattr(switch_req, "explanation", "") or ""),
                }
            )

        await send(
            {
                "type": "ui_state_patch",
                "patch": patch,
                "operations": ops_payload,
                "applied_operations": applied_ops_payload,
                "applied_patch": applied_patch,
                "source": "conversation",
                "actor": "control_parser",
                "intent_type": "ui_control",
                "confidence": float(control_confidence),
                "no_op": bool(len(applied_ops_payload) == 0),
                "summary": confirm_text,
            }
        )
        if runtime_model is not None:
            await send({"type": "model_runtime", "runtime": runtime_model})

        await send({"type": "text", "text": confirm_text})
        usage_obj = deps.normalize_usage_payload({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        await send(
            {
                "type": "done",
                "iterations": 1,
                "tool_calls": 0,
                "usage": usage_obj,  # legacy alias for run_usage
                "run_usage": usage_obj,
                "session_usage": usage_obj,
                "token_report": {
                    "token_economy": token_economy_meta,
                    "control": control_meta,
                },
                "token_economy": token_economy_meta,
                "control": control_meta,
                "runtime_model": runtime_model,
                "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            }
        )
        if run_store_enabled:
            try:
                run_store_mod.finalize_run(
                    run_id,
                    ok=True,
                    error=None,
                    iterations=1,
                    tool_calls=0,
                    usage=usage_obj,
                )
            except Exception as e:
                log.warning("Run store finalize failed (ui control): %s", e)
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception as e:
                log.debug("Run writer close failed (ui control): %s", e)
        try:
            await resp.write_eof()
        except Exception as eof_err:
            log.debug("Failed to close chat stream cleanly: %s", eof_err)
    return resp
