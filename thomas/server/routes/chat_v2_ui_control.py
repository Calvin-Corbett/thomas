"""Conversational UI-control turn handling for Chat V2."""

from __future__ import annotations

import secrets
from typing import Any

from aiohttp import web

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.action_receipt import ActionReceipt
from thomas.server.routes.chat_v2_usage import session_usage_for_session, terminal_usage_fields


def chat_stream_headers(request: web.Request) -> dict[str, str]:
    headers = {
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Thomas-Chat-Engine": "v2",
    }
    if request.path == "/api/chat":
        headers.update({"Deprecation": "true", "Link": '</api/v2/chat>; rel="successor-version"'})
    return headers


async def handle_ui_control_turn(
    request: web.Request,
    *,
    payload: dict[str, Any],
    sid: str,
    prompt: str,
    mode: str,
    autonomy_level: int,
    conversation: ConversationManager,
    session_store: SessionStore,
    meta: SessionMeta,
    control: Any,
    token_economy_meta: dict[str, str],
) -> web.StreamResponse:
    requested_patch = dict(getattr(control, "patch", None) or {})
    operations = [dict(item) for item in list(getattr(control, "operations", None) or [])]
    previous: dict[str, Any] = {
        "mode": str(mode or "auto").strip().lower(),
        "autonomy_level": int(autonomy_level),
        "settings": dict(payload.get("settings") or {}),
    }
    if str(requested_patch.get("mode") or "").strip().lower() == "batch":
        requested_patch["mode"] = "max"
        for operation in operations:
            if str(operation.get("key") or "") == "mode":
                operation.update(value="max", summary="mode to max (batch retired)")
    settings_patch = requested_patch.get("settings")
    if not isinstance(settings_patch, dict):
        settings_patch = {}
    if "autonomyLevel" in settings_patch:
        settings_patch["autonomyLevel"] = max(1, min(4, int(settings_patch["autonomyLevel"])))
        meta.autonomy_level = int(settings_patch["autonomyLevel"])
        requested_patch["settings"] = settings_patch
    applied_operations: list[dict[str, Any]] = []
    applied_patch: dict[str, Any] = {}
    for index, operation in enumerate(operations):
        item = dict(operation)
        key = str(item.get("key") or "").strip()
        desired = item.get("value")
        if key == "mode":
            before = previous["mode"]
            desired = str(requested_patch.get("mode") or desired or "").strip().lower()
            applied = bool(desired and desired != before)
            if applied:
                applied_patch["mode"] = desired
        elif key == "autonomyLevel":
            before = previous["autonomy_level"]
            desired = int(settings_patch.get("autonomyLevel", desired or before))
            applied = desired != before
            if applied:
                applied_patch.setdefault("settings", {})["autonomyLevel"] = desired
        else:
            before = previous["settings"].get(key)
            desired = settings_patch.get(key, desired)
            applied = key in settings_patch and desired != before
            if applied:
                applied_patch.setdefault("settings", {})[key] = desired
        item.update(before=before, after=desired, applied=applied, applied_source="v2")
        operations[index] = item
        if applied:
            applied_operations.append(item)
    no_op = not applied_operations
    confirmation = (
        "No configuration changes were applied (already set)."
        if no_op
        else str(getattr(control, "confirmation", "") or "Updated requested settings.")
    )
    if requested_patch.get("mode") == "max" and any(
        str(operation.get("key") or "") == "mode" and operation.get("value") == "max" for operation in operations
    ):
        confirmation = "Updated mode to max. The duplicate batch execution mode is retired."
    receipt = ActionReceipt(
        action_id=f"control-{secrets.token_urlsafe(8)}",
        session_id=sid,
        action="ui.configure",
        state="completed",
        ok=True,
        evidence={
            "requested_patch": requested_patch,
            "applied_patch": applied_patch,
            "previous": previous,
            "rollback": previous,
        },
        reversible=True,
        approval="not_required",
    ).to_dict()
    conversation = conversation.append_message("user", prompt)
    conversation = conversation.append_message("assistant", confirmation, metadata={"receipt": receipt})
    await session_store.save(sid, conversation, meta, force=True)
    response = web.StreamResponse(status=200, headers=chat_stream_headers(request))
    await response.prepare(request)
    dispatcher = EventDispatcher(response.write)
    await dispatcher.emit(
        {
            "type": "route",
            "route": {"path": "control", "confidence": 1.0},
            "mode": mode,
            "token_economy": dict(token_economy_meta),
            "autonomy_level": autonomy_level,
        }
    )
    await dispatcher.emit({"type": "operator_action", **receipt})
    control_meta = {
        "actor": "control_parser",
        "intent_type": "ui_control",
        "operations_total": len(operations),
        "operations_applied": len(applied_operations),
        "no_op": no_op,
        "applied_patch": applied_patch,
    }
    await dispatcher.emit(
        {
            "type": "ui_state_patch",
            "patch": requested_patch,
            "operations": operations,
            "applied_operations": applied_operations,
            "applied_patch": applied_patch,
            "actor": "control_parser",
            "intent_type": "ui_control",
            "no_op": no_op,
            "summary": confirmation,
            "receipt": receipt,
        }
    )
    await dispatcher.emit_text(confirmation)
    usage_fields = terminal_usage_fields(
        session_usage=session_usage_for_session(
            request.app,
            sid,
            persisted_total=meta.token_spend,
        )
    )
    await dispatcher.emit_done(
        session_id=sid,
        conversation_version=conversation.version,
        thinking_summary="ui_control",
        iterations=1,
        tool_calls=0,
        **usage_fields,
        token_economy=dict(token_economy_meta),
        token_report={"control": control_meta, "token_economy": dict(token_economy_meta)},
        control=control_meta,
    )
    await response.write_eof()
    return response


_chat_stream_headers = chat_stream_headers
_handle_ui_control_turn = handle_ui_control_turn

__all__ = ["_chat_stream_headers", "_handle_ui_control_turn", "chat_stream_headers", "handle_ui_control_turn"]
