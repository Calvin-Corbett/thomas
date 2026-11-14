"""Approve, steer and stop exactly the requested Code run."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from aiohttp import web

from .evolve_agent_http_support import validate_active_run_request
from .evolve_agent_page_steer import watch_page_steer
from .evolve_agent_run_state import (
    APP_EVOLVE_AGENT_APPROVALS,
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
)
from .evolve_agent_runtime import _await_recording, _mark_steer_requested, _mark_stop_requested, _terminate_process


def build_evolve_agent_control_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    _slot_for_run_id: Callable[[str], dict[str, Any] | None],
    _running: Callable[[], bool],
    _kill_tree: Callable[[Any], None],
) -> dict[str, Any]:
    async def approve(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        approval_id = str((body or {}).get("approval_id") or "").strip()
        approvals = app[APP_EVOLVE_AGENT_APPROVALS]
        approval = approvals.get(approval_id)
        if not isinstance(approval, dict) or float(approval.get("expires_at") or 0) < time.time():
            return web.json_response({"ok": False, "error": "approval is missing or expired"}, status=404)
        if approval.get("state") != "pending":
            return web.json_response({"ok": False, "error": "approval is no longer pending"}, status=409)
        approval["state"] = "approved"
        approval["approved_at"] = time.time()
        return web.json_response(
            {
                "ok": True,
                "approval": {
                    key: value for key, value in approval.items() if key not in {"message_hash", "action_hash"}
                },
            }
        )

    async def steer(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty steering message"}, status=400)
        # Steer exactly the requested run when several are live.
        slot = _slot_for_run_id(str((body or {}).get("run_id") or ""))
        if slot is not None:
            proc = (slot.get("session") or {}).get("proc")
            if proc is None or proc.returncode is not None:
                return web.json_response({"ok": False, "error": "that Code run is not running"}, status=409)
            _mark_steer_requested(proc)
            asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
            watch_page_steer(app, slot.get("session"), slot.get("drain"), message)
            return web.json_response(
                {"ok": True, "stop_requested": True, "restart_required": True, "message": message}, status=202
            )
        if not _running():
            return web.json_response({"ok": False, "error": "no Code task is running"}, status=409)
        stale = validate_active_run_request(body, app.get(APP_EVOLVE_AGENT_SESSION))
        if stale is not None:
            return stale
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        if proc is not None and proc.returncode is None:
            _mark_steer_requested(proc)
            asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
        watch_page_steer(app, app.get(APP_EVOLVE_AGENT_SESSION), app.get(APP_EVOLVE_AGENT_DRAIN), message)
        return web.json_response(
            {"ok": True, "stop_requested": True, "restart_required": True, "message": message}, status=202
        )

    async def stop(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        from thomas.server.landed_code_resume import cancel

        session = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        cancel(app, str((body or {}).get("run_id") or session.get("run_id") or ""))
        # Resolve the slot for the REQUESTED run so stopping targets exactly
        # that run even when several are live.
        slot = _slot_for_run_id(str((body or {}).get("run_id") or ""))
        if slot is not None:
            proc = (slot.get("session") or {}).get("proc")
            _mark_stop_requested(proc)
            receipt = await _terminate_process(proc)
            if receipt["termination_confirmed"]:
                receipt.update(await _await_recording(slot.get("drain")))
            status_code = (
                200 if receipt["termination_confirmed"] else 202 if receipt["state"] == "termination_pending" else 409
            )
            return web.json_response(receipt, status=status_code)
        if _running():
            stale = validate_active_run_request(body, app.get(APP_EVOLVE_AGENT_SESSION))
            if stale is not None:
                return stale
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        _mark_stop_requested(proc)
        receipt = await _terminate_process(proc)
        if receipt["termination_confirmed"]:
            receipt.update(await _await_recording(app.get(APP_EVOLVE_AGENT_DRAIN)))
        status_code = (
            200 if receipt["termination_confirmed"] else 202 if receipt["state"] == "termination_pending" else 409
        )
        return web.json_response(receipt, status=status_code)

    return {"approve": approve, "steer": steer, "stop": stop}
