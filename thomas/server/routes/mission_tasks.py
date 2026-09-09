"""Mission task CRUD operations - task creation, listing, status updates, and cancellation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.autonomy.scheduler import compute_next_run

log = logging.getLogger(__name__)

from .mission_support import (
    _MISSION_ALLOWED_JOB_KINDS,
    _MISSION_ALLOWED_RISK_CLASSES,
    _coerce_bool,
    _coerce_int,
    _mission_job_payload,
    _mission_normalize_schedule,
    _parse_iso_datetime,
)


def build_mission_task_handlers(
    app: web.Application,
    _mission_require_store: Any,
    _mission_wakeup_engine: Any,
    *,
    require_api_access: Callable[[web.Request], None],
) -> tuple:
    """Build task management route handlers.

    Args:
        app: aiohttp Application instance
        _mission_require_store: Async callable to get/ensure autonomy store
        _mission_wakeup_engine: Callable to wake the engine after job changes

    Returns:
        Tuple of route handler coroutines
    """

    async def api_mission_jobs(request: web.Request) -> web.Response:
        require_api_access(request)
        """List all jobs with optional filtering by status, kind, parent_id, session_id."""
        q = request.query
        status = str(q.get("status") or "").strip() or None
        kind = str(q.get("kind") or "").strip() or None
        parent_id = str(q.get("parent_id") or "").strip() or None
        session_id = str(q.get("session_id") or "").strip() or None
        limit = _coerce_int(q.get("limit"), 200)
        offset = _coerce_int(q.get("offset"), 0)
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        filters = {
            "status": status or "",
            "kind": kind or "",
            "parent_id": parent_id or "",
            "session_id": session_id or "",
            "limit": limit,
            "offset": offset,
        }

        store = app.get("autonomy_store")
        if store is None:
            return web.json_response(
                {
                    "ok": True,
                    "jobs": [],
                    "count": 0,
                    "filters": filters,
                    "unavailable": True,
                    "reason": "autonomy store is not available",
                },
                dumps=lambda x: json.dumps(x, ensure_ascii=False),
            )

        try:
            jobs = list(
                store.list_jobs(
                    status=status,
                    kind=kind,
                    parent_id=parent_id,
                    session_id=session_id,
                    limit=limit,
                    offset=offset,
                )
                or []
            )
        except KeyError as exc:
            log.warning("mission jobs list: query failed: %s", exc)
            raise web.HTTPNotFound(text="job query failed") from exc
        except ValueError as exc:
            log.warning("mission jobs list: invalid filter parameters: %s", exc)
            raise web.HTTPBadRequest(text="invalid filter parameters") from exc

        rows = [_mission_job_payload(job) for job in jobs]
        return web.json_response(
            {
                "ok": True,
                "jobs": rows,
                "count": len(rows),
                "filters": filters,
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_mission_job_create(request: web.Request) -> web.Response:
        require_api_access(request)
        """Create a new task/job with specified name, kind, and payload."""
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("mission job create: invalid json body: %s", exc)
            raise web.HTTPBadRequest(text="invalid json body") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="json body must be an object")

        name = str(payload.get("name") or "").strip() or "Mission Task"
        kind = str(payload.get("kind") or "workflow_task").strip().lower() or "workflow_task"
        if kind not in _MISSION_ALLOWED_JOB_KINDS:
            allowed = ", ".join(sorted(_MISSION_ALLOWED_JOB_KINDS))
            raise web.HTTPBadRequest(text=f"kind must be one of: {allowed}")

        job_payload = payload.get("payload")
        if not isinstance(job_payload, dict):
            job_payload = {}
        else:
            job_payload = dict(job_payload)

        if kind in {"workflow_task", "autonomy_task"}:
            goal = (
                str(payload.get("goal") or "").strip()
                or str(payload.get("prompt") or "").strip()
                or str(job_payload.get("goal") or "").strip()
                or str(job_payload.get("prompt") or "").strip()
                or str(job_payload.get("task") or "").strip()
            )
            if not goal:
                raise web.HTTPBadRequest(text="goal or prompt is required for workflow/autonomy tasks")
            job_payload["goal"] = goal
            if not str(job_payload.get("prompt") or "").strip():
                job_payload["prompt"] = goal
            workflow = (
                str(payload.get("workflow") or "").strip().lower()
                or str(job_payload.get("workflow") or "").strip().lower()
            )
            if workflow:
                job_payload["workflow"] = workflow
            profile = str(payload.get("profile") or "").strip() or str(job_payload.get("profile") or "").strip()
            if profile:
                job_payload["profile"] = profile
            model_id = str(payload.get("model_id") or "").strip() or str(job_payload.get("model_id") or "").strip()
            if model_id:
                job_payload["model_id"] = model_id

        elif kind == "evolve_session":
            goal = (
                str(payload.get("goal") or "").strip()
                or str(payload.get("prompt") or "").strip()
                or str(job_payload.get("goal") or "").strip()
                or str(job_payload.get("prompt") or "").strip()
            )
            if goal:
                job_payload["goal"] = goal
                if not str(job_payload.get("prompt") or "").strip():
                    job_payload["prompt"] = goal
            profile = str(payload.get("profile") or "").strip() or str(job_payload.get("profile") or "").strip()
            if profile:
                job_payload["profile"] = profile
            model_id = str(payload.get("model_id") or "").strip() or str(job_payload.get("model_id") or "").strip()
            if model_id:
                job_payload["model_id"] = model_id
            passes = _coerce_int(payload.get("passes") or job_payload.get("passes"), 1)
            if passes > 0:
                job_payload["passes"] = max(1, min(passes, 8))
            timeout_seconds = _coerce_int(payload.get("timeout_seconds") or job_payload.get("timeout_seconds"), 1800)
            if timeout_seconds > 0:
                job_payload["timeout_seconds"] = max(60, min(timeout_seconds, 7200))
            job_payload["promote_on_pass"] = _coerce_bool(
                payload.get("promote_on_pass") if "promote_on_pass" in payload else job_payload.get("promote_on_pass"),
                default=False,
            )
        elif kind == "reminder":
            msg = (
                str(payload.get("message") or "").strip()
                or str(payload.get("prompt") or "").strip()
                or str(job_payload.get("message") or "").strip()
                or str(job_payload.get("text") or "").strip()
            )
            if msg:
                job_payload["message"] = msg
                if not str(job_payload.get("text") or "").strip():
                    job_payload["text"] = msg
        elif kind == "daily_briefing":
            prompt = str(payload.get("prompt") or "").strip() or str(job_payload.get("prompt") or "").strip()
            if prompt:
                job_payload["prompt"] = prompt

        run_at = _parse_iso_datetime(payload.get("run_at"))
        schedule = _mission_normalize_schedule(payload.get("schedule"), run_at=run_at)
        now = datetime.now(timezone.utc)
        next_run_at: datetime | None
        if schedule is None:
            next_run_at = run_at or now
        else:
            try:
                next_run_at = compute_next_run(schedule, now)
            except ValueError as exc:
                log.warning("mission job create: invalid schedule: %s", exc)
                raise web.HTTPBadRequest(text="invalid schedule") from exc
            if next_run_at is None:
                raise web.HTTPBadRequest(text="schedule does not produce a future run time")
            if next_run_at.tzinfo is None:
                next_run_at = next_run_at.replace(tzinfo=timezone.utc)
            else:
                next_run_at = next_run_at.astimezone(timezone.utc)

        risk_class = str(payload.get("risk_class") or "low").strip().lower() or "low"
        if risk_class not in _MISSION_ALLOWED_RISK_CLASSES:
            risk_class = "low"
        requires_approval = _coerce_bool(payload.get("requires_approval"), default=False)
        parent_id = str(payload.get("parent_id") or "").strip() or None
        session_id = str(payload.get("session_id") or "").strip() or None

        store = await _mission_require_store(auto_enable=True)

        try:
            job = store.create_job(
                name=name,
                kind=kind,
                payload=job_payload,
                schedule=schedule,
                next_run_at=next_run_at,
                risk_class=risk_class,
                requires_approval=requires_approval,
                parent_id=parent_id,
                session_id=session_id,
            )
        except ValueError as exc:
            log.warning("mission job create: invalid job parameters: %s", exc)
            raise web.HTTPBadRequest(text="invalid job parameters") from exc

        _mission_wakeup_engine()
        return web.json_response(
            {
                "ok": True,
                "job": _mission_job_payload(job),
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_mission_job_cancel(request: web.Request) -> web.Response:
        require_api_access(request)
        """Cancel an existing job by job_id."""
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.cancel_job(job_id, actor="mission_control")
        except KeyError:
            raise web.HTTPNotFound(text="job not found") from None

        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "cancel"})

    async def api_mission_job_run_now(request: web.Request) -> web.Response:
        require_api_access(request)
        """Immediately queue a job for execution by setting status to queued."""
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.set_job_status(
                job_id,
                "queued",
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        except KeyError:
            raise web.HTTPNotFound(text="job not found") from None

        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "run_now"})

    async def api_mission_job_requeue(request: web.Request) -> web.Response:
        require_api_access(request)
        """Reset a job to queued status, clearing errors and result history."""
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.set_job_status(
                job_id,
                "queued",
                error=None,
                result=None,
                attempts=0,
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        except KeyError:
            raise web.HTTPNotFound(text="job not found") from None

        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "requeue"})

    return (
        api_mission_jobs,
        api_mission_job_create,
        api_mission_job_cancel,
        api_mission_job_run_now,
        api_mission_job_requeue,
    )
