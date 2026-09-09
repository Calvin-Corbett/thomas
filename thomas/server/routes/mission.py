"""Mission Control routes and benchmark UI APIs - facade for modular mission handlers.

This module orchestrates route registration by importing from specialized mission modules:
- mission_tasks.py: Task CRUD and management
- mission_cron.py: Scheduled/autopilot task management
- mission_approvals.py: Approval workflows
- mission_workflows.py: Workflow orchestration and content hub
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from .mission_approvals import build_mission_approvals_handlers
from .mission_autonomy_runtime import build_mission_autonomy_helpers
from .mission_benchmark_routes import register_mission_benchmark_routes
from .mission_control_routes import build_mission_control_routes
from .mission_cron import build_mission_cron_handlers
from .mission_support import _discover_repo_root
from .mission_tasks import build_mission_task_handlers
from .mission_workflows import build_mission_workflow_handlers

APP_MISSION_REQUIRE_STORE = web.AppKey("mission_require_store", object)
APP_MISSION_WAKEUP_ENGINE = web.AppKey("mission_wakeup_engine", object)


async def _serve_mission_page(web_dir: Path) -> web.StreamResponse:
    """Serve the mission.html page."""
    from .mission_support import _serve_versioned_page

    return _serve_versioned_page(web_dir / "mission.html")


def register_mission_routes(
    app: web.Application,
    *,
    web_dir: Path,
    require_api_access: Callable[[web.Request], None],
    run_store_enabled_key: Any,
    run_store_module_key: Any,
) -> None:
    """Register all mission control routes.

    Coordinates route registration across multiple specialized modules.

    Args:
        app: aiohttp Application instance
        web_dir: Path to web assets directory
        require_api_access: Callable to enforce API access control
        run_store_enabled_key: App key for run store enabled flag
        run_store_module_key: App key for run store module
    """
    repo_root = _discover_repo_root(web_dir)
    runs_dir = (repo_root / "demo" / "agentic-runs").resolve()

    # Build mission control helpers
    api_mission_control, api_mission_stream, _mission_approvals_payload = build_mission_control_routes(
        app,
        require_api_access=require_api_access,
        run_store_enabled_key=run_store_enabled_key,
        run_store_module_key=run_store_module_key,
    )

    _mission_bootstrap_autonomy, _mission_require_store, _mission_wakeup_engine = build_mission_autonomy_helpers(app)
    app[APP_MISSION_REQUIRE_STORE] = _mission_require_store
    app[APP_MISSION_WAKEUP_ENGINE] = _mission_wakeup_engine

    # Build handlers from modular mission modules
    (
        api_mission_jobs,
        api_mission_job_create,
        api_mission_job_cancel,
        api_mission_job_run_now,
        api_mission_job_requeue,
    ) = build_mission_task_handlers(
        app,
        _mission_require_store,
        _mission_wakeup_engine,
        require_api_access=require_api_access,
    )

    (
        api_mission_autopilot_bootstrap,
        api_mission_autopilot_objective_create,
        api_mission_autopilot_objectives,
        api_mission_autopilot_objective_stop,
    ) = build_mission_cron_handlers(
        app,
        _mission_bootstrap_autonomy,
        _mission_require_store,
        _mission_wakeup_engine,
        require_api_access=require_api_access,
    )

    (
        api_mission_autonomy_approval_decide,
        api_mission_guardrails_approval_resolve,
    ) = build_mission_approvals_handlers(
        app,
        _mission_require_store,
        _mission_wakeup_engine,
        require_api_access=require_api_access,
    )

    (
        api_mission_content_hub,
        api_mission_alert_notify,
    ) = build_mission_workflow_handlers(
        app,
        run_store_enabled_key,
        run_store_module_key,
        _mission_approvals_payload,
    )

    # Register all routes
    async def mission_page(_request: web.Request) -> web.StreamResponse:
        return await _serve_mission_page(web_dir)

    existing_paths = {str(getattr(resource, "canonical", "") or "") for resource in app.router.resources()}
    if "/mission" not in existing_paths:
        app.router.add_get("/mission", mission_page)
    app.router.add_get("/api/mission/control", api_mission_control)
    app.router.add_get("/api/mission/content-hub", api_mission_content_hub)
    app.router.add_get("/api/mission/stream", api_mission_stream)
    app.router.add_get("/api/mission/jobs", api_mission_jobs)
    app.router.add_post("/api/mission/jobs", api_mission_job_create)
    app.router.add_post("/api/mission/jobs/{job_id}/cancel", api_mission_job_cancel)
    app.router.add_post("/api/mission/jobs/{job_id}/run_now", api_mission_job_run_now)
    app.router.add_post("/api/mission/jobs/{job_id}/requeue", api_mission_job_requeue)
    app.router.add_post("/api/mission/autopilot/bootstrap", api_mission_autopilot_bootstrap)
    app.router.add_get("/api/mission/autopilot/objectives", api_mission_autopilot_objectives)
    app.router.add_post("/api/mission/autopilot/objectives", api_mission_autopilot_objective_create)
    app.router.add_post(
        "/api/mission/autopilot/objectives/{objective_id}/stop",
        api_mission_autopilot_objective_stop,
    )
    app.router.add_post(
        "/api/mission/approvals/autonomy/{approval_id}/decision",
        api_mission_autonomy_approval_decide,
    )
    app.router.add_post(
        "/api/mission/approvals/guardrails/resolve",
        api_mission_guardrails_approval_resolve,
    )
    app.router.add_post("/api/mission/alerts/notify", api_mission_alert_notify)

    # Benchmark routes registration
    benchmark_jobs = {}
    benchmark_tasks = {}
    benchmark_procs = {}
    import asyncio

    benchmark_lock = asyncio.Lock()

    register_mission_benchmark_routes(
        app,
        repo_root=repo_root,
        runs_dir=runs_dir,
        require_api_access=require_api_access,
        benchmark_jobs=benchmark_jobs,
        benchmark_tasks=benchmark_tasks,
        benchmark_procs=benchmark_procs,
        benchmark_lock=benchmark_lock,
    )
