"""Mission scheduled/cron task management - autopilot objectives and recurring tasks."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.autonomy.scheduler import compute_next_run

from .mission_support import (
    _AUTOPILOT_OBJECTIVE_ID_RE,
    _MISSION_ALLOWED_RISK_CLASSES,
    _MISSION_TERMINAL_JOB_STATUSES,
    _autopilot_objective_id,
    _autopilot_schedule_from_payload,
    _coerce_bool,
    _coerce_int,
    _coerce_iso,
    _iso_to_epoch,
    _mission_job_payload,
)


def build_mission_cron_handlers(
    app: web.Application,
    _mission_bootstrap_autonomy: Any,
    _mission_require_store: Any,
    _mission_wakeup_engine: Any,
    *,
    require_api_access: Callable[[web.Request], None],
) -> tuple:
    """Build scheduled/cron task management route handlers.

    Args:
        app: aiohttp Application instance
        _mission_bootstrap_autonomy: Async callable to bootstrap autonomy runtime
        _mission_require_store: Async callable to get/ensure autonomy store
        _mission_wakeup_engine: Callable to wake the engine after job changes

    Returns:
        Tuple of route handler coroutines
    """

    async def api_mission_autopilot_bootstrap(request: web.Request) -> web.Response:
        require_api_access(request)
        """Bootstrap the autonomy runtime for autopilot objectives."""
        enabled = await _mission_bootstrap_autonomy()
        store = app.get("autonomy_store")
        engine = app.get("autonomy_engine")
        if not enabled or store is None or engine is None:
            raise web.HTTPInternalServerError(text="unable to bootstrap autonomy runtime")
        return web.json_response(
            {
                "ok": True,
                "enabled": True,
                "engine": {
                    "running": bool(getattr(engine, "is_running", False)),
                    "worker_id": str(getattr(engine, "worker_id", "") or ""),
                },
                "store": {
                    "db_path": str(getattr(store, "db_path", "") or ""),
                },
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_mission_autopilot_objective_create(request: web.Request) -> web.Response:
        require_api_access(request)
        """Create a new autopilot objective (recurring/scheduled task)."""
        try:
            payload = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text=f"invalid json: {type(exc).__name__}: {exc}") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="json body must be an object")

        auto_enable = _coerce_bool(payload.get("auto_enable"), default=True)

        goal = (
            str(payload.get("goal") or "").strip()
            or str(payload.get("prompt") or "").strip()
            or str(payload.get("task") or "").strip()
        )
        if not goal:
            raise web.HTTPBadRequest(text="goal is required")

        kind = str(payload.get("kind") or "workflow_task").strip().lower() or "workflow_task"
        if kind not in {"workflow_task", "autonomy_task"}:
            raise web.HTTPBadRequest(text="kind must be 'workflow_task' or 'autonomy_task'")

        objective_id = _autopilot_objective_id(payload.get("objective_id"), goal=goal)
        schedule, cadence = _autopilot_schedule_from_payload(payload)
        now = datetime.now(timezone.utc)
        start_immediately = _coerce_bool(payload.get("start_immediately"), default=True)
        if start_immediately:
            next_run_at = now
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

        session_id = str(payload.get("session_id") or "").strip() or None
        requires_approval = _coerce_bool(payload.get("requires_approval"), default=False)
        profile = str(payload.get("profile") or "").strip()
        model_id = str(payload.get("model_id") or "").strip()
        workflow = str(payload.get("workflow") or "orchestrator_worker").strip().lower() or "orchestrator_worker"
        autonomy_level = max(1, min(4, _coerce_int(payload.get("autonomy_level"), 4)))
        worker_count = max(1, min(8, _coerce_int(payload.get("worker_count"), 3)))
        every_seconds = 0
        with contextlib.suppress(ValueError):
            every_seconds = int((schedule or {}).get("every_seconds") or 0)

        job_payload = payload.get("payload")
        if not isinstance(job_payload, dict):
            job_payload = {}
        else:
            job_payload = dict(job_payload)

        job_payload["goal"] = goal
        job_payload["prompt"] = str(job_payload.get("prompt") or "").strip() or goal
        job_payload["task"] = str(job_payload.get("task") or "").strip() or goal
        job_payload["workflow"] = workflow
        job_payload["autonomy_level"] = int(autonomy_level)
        job_payload["worker_count"] = int(worker_count)
        if profile:
            job_payload["profile"] = profile
        if model_id:
            job_payload["model_id"] = model_id
        job_payload["autopilot"] = {
            "enabled": True,
            "objective_id": objective_id,
            "cadence": cadence,
            "every_seconds": int(every_seconds) if every_seconds > 0 else 0,
            "created_at": now.isoformat(),
        }

        name = str(payload.get("name") or "").strip() or f"Autopilot: {goal[:64]}"
        store = await _mission_require_store(auto_enable=auto_enable)

        try:
            job = store.create_job(
                name=name,
                kind=kind,
                payload=job_payload,
                schedule=schedule,
                next_run_at=next_run_at,
                risk_class=risk_class,
                requires_approval=requires_approval,
                parent_id=None,
                session_id=session_id,
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(text=f"invalid autopilot parameters: {exc}") from exc

        _mission_wakeup_engine()
        return web.json_response(
            {
                "ok": True,
                "objective_id": objective_id,
                "job": _mission_job_payload(job),
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_mission_autopilot_objectives(request: web.Request) -> web.Response:
        require_api_access(request)
        """List all autopilot objectives with optional filtering."""
        q = request.query
        limit = max(1, min(_coerce_int(q.get("limit"), 180), 500))
        objective_filter = str(q.get("objective_id") or "").strip()
        active_only = _coerce_bool(q.get("active_only"), default=True)

        store = app.get("autonomy_store")
        if store is None:
            return web.json_response(
                {
                    "ok": True,
                    "objectives": [],
                    "count": 0,
                    "unavailable": True,
                    "reason": "autonomy store is not available",
                },
                dumps=lambda x: json.dumps(x, ensure_ascii=False),
            )

        try:
            jobs = list(store.list_jobs(limit=max(limit * 3, 180), offset=0) or [])
        except KeyError as exc:
            raise web.HTTPInternalServerError(text=f"unable to list autopilot objectives: {exc}") from exc

        rows: list[dict[str, Any]] = []
        for job in jobs:
            payload_obj = getattr(job, "payload", None)
            payload_dict = payload_obj if isinstance(payload_obj, dict) else {}
            auto = payload_dict.get("autopilot")
            auto_dict = auto if isinstance(auto, dict) else {}
            if not bool(auto_dict.get("enabled")):
                continue
            objective_id = str(auto_dict.get("objective_id") or "").strip()
            if not objective_id:
                continue
            if objective_filter and objective_id != objective_filter:
                continue
            status = str(getattr(job, "status", "") or "").strip().lower() or "unknown"
            if active_only and status in _MISSION_TERMINAL_JOB_STATUSES:
                continue
            rows.append(
                {
                    "objective_id": objective_id,
                    "job_id": str(getattr(job, "id", "") or ""),
                    "name": str(getattr(job, "name", "") or ""),
                    "goal": str(payload_dict.get("goal") or payload_dict.get("prompt") or "").strip(),
                    "status": status,
                    "kind": str(getattr(job, "kind", "") or ""),
                    "cadence": str(auto_dict.get("cadence") or ""),
                    "every_seconds": int(auto_dict.get("every_seconds") or 0),
                    "next_run_at": _coerce_iso(getattr(job, "next_run_at", None)),
                    "updated_at": _coerce_iso(getattr(job, "updated_at", None)),
                    "session_id": str(getattr(job, "session_id", "") or ""),
                    "requires_approval": bool(getattr(job, "requires_approval", False)),
                }
            )

        rows.sort(key=lambda row: _iso_to_epoch(row.get("updated_at")), reverse=True)
        rows = rows[:limit]
        return web.json_response(
            {
                "ok": True,
                "objectives": rows,
                "count": len(rows),
                "filters": {
                    "objective_id": objective_filter,
                    "active_only": bool(active_only),
                    "limit": int(limit),
                },
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_mission_autopilot_objective_stop(request: web.Request) -> web.Response:
        require_api_access(request)
        """Stop all jobs associated with an autopilot objective."""
        store = await _mission_require_store()
        objective_id = str(request.match_info.get("objective_id") or "").strip()
        if not objective_id:
            raise web.HTTPBadRequest(text="missing objective_id")
        if not _AUTOPILOT_OBJECTIVE_ID_RE.fullmatch(objective_id):
            raise web.HTTPBadRequest(text="invalid objective_id")

        try:
            jobs = list(store.list_jobs(limit=2000, offset=0) or [])
        except KeyError as exc:
            raise web.HTTPInternalServerError(text=f"unable to read objectives: {exc}") from exc

        matched = 0
        cancelled = 0
        for job in jobs:
            payload_obj = getattr(job, "payload", None)
            payload_dict = payload_obj if isinstance(payload_obj, dict) else {}
            auto = payload_dict.get("autopilot")
            auto_dict = auto if isinstance(auto, dict) else {}
            if str(auto_dict.get("objective_id") or "").strip() != objective_id:
                continue
            matched += 1
            status = str(getattr(job, "status", "") or "").strip().lower()
            if status in _MISSION_TERMINAL_JOB_STATUSES:
                continue
            with contextlib.suppress(Exception):
                store.cancel_job(str(getattr(job, "id", "") or ""), actor="mission_autopilot")
                cancelled += 1

        if matched == 0:
            raise web.HTTPNotFound(text="objective not found")

        _mission_wakeup_engine()
        return web.json_response(
            {
                "ok": True,
                "objective_id": objective_id,
                "matched_jobs": int(matched),
                "cancelled_jobs": int(cancelled),
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    return (
        api_mission_autopilot_bootstrap,
        api_mission_autopilot_objective_create,
        api_mission_autopilot_objectives,
        api_mission_autopilot_objective_stop,
    )
