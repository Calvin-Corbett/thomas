"""Mission approval workflows - autonomy task approval and guardrails approval resolution."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_APPROVALS_BROKER

log = logging.getLogger(__name__)


def _resolve_approvals_broker(app: web.Application):
    broker = app.get(APP_APPROVALS_BROKER)
    if broker is not None:
        return broker

    state = getattr(app, "_state", None)
    if isinstance(state, dict):
        broker = state.get("approvals")
        if broker is not None:
            state[APP_APPROVALS_BROKER] = broker
            return broker

    broker = app.get("approvals")
    if broker is not None:
        app[APP_APPROVALS_BROKER] = broker
    return broker


def _parse_decision(payload: dict[str, Any], *, default: bool | None = None) -> bool | None:
    if not isinstance(payload, dict):
        return default

    if "decision" in payload:
        value = payload.get("decision")
    elif "approve" in payload:
        value = payload.get("approve")
    else:
        value = None

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "ok", "allow", "approve"):
            return True
        if v in ("0", "false", "no", "fail", "failed", "deny", "reject"):
            return False
    return default


def _parse_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        log.warning("Failed to parse JSON request body", exc_info=True)
        raise web.HTTPBadRequest(text="invalid json") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


def build_mission_approvals_handlers(
    app: web.Application,
    _mission_require_store: Any,
    _mission_wakeup_engine: Any,
    *,
    require_api_access: Callable[[web.Request], None],
) -> tuple:
    """Build approval workflow route handlers.

    Args:
        app: aiohttp Application instance
        _mission_require_store: Async callable to get/ensure autonomy store
        _mission_wakeup_engine: Callable to wake the engine after job changes

    Returns:
        Tuple of route handler coroutines
    """

    async def api_mission_autonomy_approval_decide(request: web.Request) -> web.Response:
        require_api_access(request)
        """Approve or deny an autonomy task approval request."""
        store = await _mission_require_store()
        approval_id = str(request.match_info.get("approval_id") or "").strip()
        if not approval_id:
            raise web.HTTPBadRequest(text="missing approval_id")
        payload = await _read_json_object(request)

        approve = _parse_decision(payload, default=None)
        if approve is None:
            raise web.HTTPBadRequest(text="missing decision")
        actor = str(payload.get("actor") or "mission_control").strip() or "mission_control"
        reason = str(payload.get("reason") or "").strip() or None
        try:
            ap = store.decide_approval(
                approval_id=approval_id,
                approve=approve,
                actor=actor,
                reason=reason,
            )
        except KeyError:
            raise web.HTTPNotFound(text="approval not found") from None

        if approve:
            with contextlib.suppress(Exception):
                store.set_job_status(
                    ap.job_id,
                    "queued",
                    approved=True,
                    requires_approval=False,
                    next_run_at=datetime.now(timezone.utc),
                    lock_clear=True,
                )
        else:
            with contextlib.suppress(Exception):
                store.cancel_job(ap.job_id, actor=actor)

        _mission_wakeup_engine()
        return web.json_response(
            {
                "ok": True,
                "approval_id": str(getattr(ap, "id", approval_id)),
                "job_id": str(getattr(ap, "job_id", "")),
                "status": str(getattr(ap, "status", "approved" if approve else "denied")),
            }
        )

    async def api_mission_guardrails_approval_resolve(request: web.Request) -> web.Response:
        require_api_access(request)
        """Resolve a guardrails approval by approving or denying a tool call."""
        broker = _resolve_approvals_broker(app)
        if broker is None:
            raise web.HTTPNotFound(text="guardrails approvals are not available")
        payload = await _read_json_object(request)

        run_id = str(payload.get("run_id") or "").strip()
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        if not run_id or not tool_call_id:
            raise web.HTTPBadRequest(text="missing run_id or tool_call_id")

        approve = _parse_decision(payload, default=None)
        if approve is None:
            raise web.HTTPBadRequest(text="missing decision")
        allow_session_tool = bool(_parse_bool(payload.get("allow_session_tool"), default=False))
        tool_name = str(payload.get("tool_name") or "").strip() or None
        session_id = str(payload.get("session_id") or "").strip() or None
        resolve_fn = getattr(broker, "resolve", None)
        if not callable(resolve_fn):
            raise web.HTTPNotFound(text="guardrails approvals are not available")

        ok = await resolve_fn(
            run_id=run_id,
            tool_call_id=tool_call_id,
            approved=approve,
            allow_session_tool=allow_session_tool,
            tool_name=tool_name,
            session_id=session_id,
        )
        if not ok:
            raise web.HTTPNotFound(text="pending approval not found")

        return web.json_response(
            {
                "ok": True,
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "decision": "approve" if approve else "deny",
                "allow_session_tool": allow_session_tool,
            }
        )

    return (
        api_mission_autonomy_approval_decide,
        api_mission_guardrails_approval_resolve,
    )
