"""Mission task CRUD operations - task creation, listing, status updates, and cancellation."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.autonomy.scheduler import compute_next_run
from thomas.core import task_bot_runtime

from .mission_support import (
    _MISSION_ALLOWED_JOB_KINDS,
    _MISSION_ALLOWED_RISK_CLASSES,
    _coerce_bool,
    _coerce_int,
    _mission_job_payload,
    _mission_normalize_schedule,
    _parse_iso_datetime,
)


def _task_bot_job_payload(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("state") or "").strip().lower() or "unknown"
    session_id = str(row.get("session_id") or row.get("conversation_id") or row.get("thread_id") or "").strip()
    return {
        "id": str(row.get("execution_id") or "").strip(),
        "source": "task_bot_execution",
        "kind": "task_manager",
        "name": str(row.get("summary") or row.get("task_id") or "Task").strip() or "Task",
        "status": status,
        "summary": str(row.get("summary") or row.get("progress_summary") or row.get("task_id") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or row.get("created_at") or "").strip(),
        "session_id": session_id,
        "task_id": str(row.get("task_id") or "").strip(),
        "execution_id": str(row.get("execution_id") or "").strip(),
        "backend_type": str(row.get("backend_type") or "task_manager").strip() or "task_manager",
        "claimed_owner": str(row.get("claimed_owner") or row.get("actor") or "").strip(),
        "proof_status": str(row.get("proof_status") or "").strip(),
        "parent_id": str(row.get("parent_execution_id") or "").strip(),
        "next_run_at": "",
        "requires_approval": False,
    }


def _task_bot_rows_for_filters(*, status: str | None, kind: str | None, session_id: str | None) -> list[dict[str, Any]]:
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind and normalized_kind not in {"task_manager", "chat_task"}:
        return []
    rows = list(task_bot_runtime.list_executions(refresh=True) or [])
    out: list[dict[str, Any]] = []
    for row in rows:
        row_status = str(row.get("state") or "").strip().lower()
        row_session = str(row.get("session_id") or row.get("conversation_id") or row.get("thread_id") or "").strip()
        if status and row_status != str(status).strip().lower():
            continue
        if session_id and row_session != str(session_id).strip():
            continue
        execution_id = str(row.get("execution_id") or "").strip()
        if execution_id:
            full = task_bot_runtime.get_execution(execution_id)
            if isinstance(full, dict) and full:
                row = full
        out.append(row)
    out.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return out


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

        task_bot_rows = _task_bot_rows_for_filters(status=status, kind=kind, session_id=session_id)
        task_bot_payloads = [_task_bot_job_payload(row) for row in task_bot_rows]

        store = app.get("autonomy_store")
        if store is None and not task_bot_payloads:
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

        jobs = []
        if store is not None:
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
                raise web.HTTPNotFound(text=f"job query failed: {exc}") from exc
            except ValueError as exc:
                raise web.HTTPBadRequest(text=f"invalid filter parameters: {exc}") from exc

        rows = [_mission_job_payload(job) for job in jobs]
        rows.extend(task_bot_payloads)
        rows.sort(
            key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
            reverse=True,
        )
        rows = rows[offset : offset + limit]
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
        except Exception as exc:
            raise web.HTTPBadRequest(text=f"invalid json: {type(exc).__name__}: {exc}") from exc
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
                raise web.HTTPBadRequest(text=f"invalid schedule: {exc}") from exc
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
            raise web.HTTPBadRequest(text=f"invalid job parameters: {exc}") from exc

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
