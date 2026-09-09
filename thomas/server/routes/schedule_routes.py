"""HTTP surface for scheduled tasks (frontier parity: Claude Code /schedule, ChatGPT tasks).

GET    /api/schedules                 -> {"tasks": [...], "health": {...}}
POST   /api/schedules                 -> {"id"?, "cron", "task", "channel"?}; 400 on a bad expression
POST   /api/schedules/{id}/pause
POST   /api/schedules/{id}/resume
POST   /api/schedules/{id}/run        -> run now
DELETE /api/schedules/{id}

Wraps ``thomas.core.scheduler.TaskScheduler``, the same object the ``thomas
cron`` CLI drives, so the page and the terminal see one list.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from aiohttp import web

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _slug(text: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")[:32] or "task"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def setup_schedule_routes(
    app: web.Application,
    *,
    scheduler: Any | None = None,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)

    def _sched() -> Any:
        if scheduler is not None:
            return scheduler
        from thomas.core.scheduler import get_scheduler

        return get_scheduler()

    def _find(sched: Any, task_id: str) -> dict[str, Any] | None:
        for task in sched.list_tasks():
            if str(task.get("id")) == task_id:
                return task
        return None

    async def list_schedules(request: web.Request) -> web.Response:
        guard(request)
        sched = _sched()
        try:
            health = sched.health()
        except (RuntimeError, OSError, AttributeError):
            health = {}
        return web.json_response({"tasks": sched.list_tasks(), "health": health})

    async def add_schedule(request: web.Request) -> web.Response:
        guard(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        cron = str(payload.get("cron") or "").strip()
        task_text = str(payload.get("task") or payload.get("goal") or "").strip()
        channel = str(payload.get("channel") or "default").strip() or "default"
        task_id = str(payload.get("id") or "").strip() or _slug(task_text)
        if not cron or not task_text:
            return web.json_response({"ok": False, "error": "cron and task are required"}, status=400)
        if not _ID.fullmatch(task_id):
            return web.json_response({"ok": False, "error": "id may use letters, digits, . _ -"}, status=400)
        sched = _sched()
        try:
            sched.add_task(task_id, cron, task_text, channel=channel)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "task": _find(sched, task_id) or {"id": task_id}})

    def _act(action: str):
        async def handler(request: web.Request) -> web.Response:
            guard(request)
            task_id = str(request.match_info.get("task_id") or "").strip()
            sched = _sched()
            if _find(sched, task_id) is None:
                return web.json_response({"ok": False, "error": "no such schedule"}, status=404)
            try:
                if action == "pause":
                    sched.pause_task(task_id)
                elif action == "resume":
                    sched.resume_task(task_id)
                elif action == "run":
                    sched.run_now(task_id)
                elif action == "remove":
                    sched.remove_task(task_id)
            except (KeyError, ValueError) as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            except RuntimeError as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=409)
            return web.json_response({"ok": True, "id": task_id, "action": action, "task": _find(sched, task_id)})

        return handler

    app.router.add_get("/api/schedules", list_schedules)
    app.router.add_post("/api/schedules", add_schedule)
    app.router.add_post("/api/schedules/{task_id}/pause", _act("pause"))
    app.router.add_post("/api/schedules/{task_id}/resume", _act("resume"))
    app.router.add_post("/api/schedules/{task_id}/run", _act("run"))
    app.router.add_delete("/api/schedules/{task_id}", _act("remove"))


__all__ = ["setup_schedule_routes"]
