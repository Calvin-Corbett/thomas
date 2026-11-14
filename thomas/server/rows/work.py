"""Jobs and Work, as a row: 76 routes, and the autonomy engine and store that Mission starts on first use.

Mission serves the jobs the Agents page lists and controls, and its approvals, autopilot objectives and benchmarks. Work serves the
Work page's apps, jobs, workflows, automations and lane proposals, and hands every automation to Mission to run. Off takes
all of these routes away. ``/mission`` is not one of them: the server's own handler redirects it to ``/agents``, so the
address still answers and the page it leads to gets 404 from its calls.

The engine is the one thing here that runs on. Mission starts it the first time a request needs it, writes it and its
store to the app, and this row owns what it started: when the row stops, once running requests have ended, the engine
stops, the store closes and the keys go. Turning the row on builds no engine: the next use builds a new one with a new
store, and a closed store is never reused. Off waits for a job the engine is running to end, unless it is forced.
An engine the server installed itself, with the autonomy switch on, is not this row's and is left running. A benchmark
that is running is cancelled with its process when the row stops. ``/api/mission/stream`` is kept open until a page
leaves, so it is named as a stream and ended when the stop begins.

``thomas.server.work_execution_adapter`` and the chat routes read the Work store from the app and find none while this is
off. ``thomas/server/rows/__init__.py`` says how a row is written. The first log line below is pinned word for word by
``tests/test_server_app_routes_init.py``, and every failure is followed by a raise, so a row that cannot register reads
failed rather than active with no routes.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_MISSION_REQUIRE_STORE, APP_MISSION_WAKEUP_ENGINE

log = logging.getLogger(__name__)


def _bridge_to_mission(view: Any) -> tuple[Any, Any, Any]:
    """The three calls Work makes into Mission: submit a job, read its status, cancel it."""
    from thomas.autonomy.scheduler import compute_next_run

    async def submit_to_mission(payload: dict[str, Any]) -> dict[str, Any]:
        require_store = view.get(APP_MISSION_REQUIRE_STORE)
        if not callable(require_store):
            raise RuntimeError("Mission store is unavailable")
        store = await require_store(auto_enable=True)
        now = datetime.now(timezone.utc)
        schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else None
        run_at = None
        if payload.get("run_at"):
            run_at = datetime.fromisoformat(str(payload["run_at"]).replace("Z", "+00:00"))
            run_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
        next_run_at = compute_next_run(schedule, now) if schedule else (run_at or now)
        if next_run_at is None:
            raise RuntimeError("Mission schedule does not produce a future run")
        job_payload = dict(payload.get("payload") or {})
        for key in ("goal", "prompt", "workflow", "profile", "model_id"):
            if payload.get(key):
                job_payload[key] = payload[key]
        delivery_id = str(job_payload.get("work_event_delivery_id") or "").strip()
        mission_job_id = hashlib.sha256(f"thomas-work:{delivery_id}".encode()).hexdigest()[:32] if delivery_id else ""
        existing_job = None
        if mission_job_id:
            try:
                existing_job = store.get_job(mission_job_id)
            except KeyError:
                existing_job = None
            if (
                existing_job is not None
                and str(existing_job.payload.get("work_event_delivery_id") or "") != delivery_id
            ):
                raise RuntimeError("Mission idempotency identity conflict")
        try:
            job = existing_job or store.create_job(
                name=str(payload.get("name") or "Work automation"),
                kind=str(payload.get("kind") or "workflow_task"),
                payload=job_payload,
                schedule=schedule,
                next_run_at=next_run_at,
                risk_class=str(payload.get("risk_class") or "low"),
                requires_approval=bool(payload.get("requires_approval")),
                parent_id=str(payload.get("parent_id") or "") or None,
                session_id=str(payload.get("session_id") or "") or None,
                job_id=mission_job_id or None,
            )
        except sqlite3.IntegrityError:
            if not mission_job_id:
                raise
            job = store.get_job(mission_job_id)
            if str(job.payload.get("work_event_delivery_id") or "") != delivery_id:
                raise RuntimeError("Mission idempotency identity conflict") from None
        wakeup = view.get(APP_MISSION_WAKEUP_ENGINE)
        if callable(wakeup):
            wakeup()
        return {"job_id": str(getattr(job, "id", "") or "")}

    async def read_mission_status(job_id: str) -> dict[str, Any] | None:
        require_store = view.get(APP_MISSION_REQUIRE_STORE)
        if not callable(require_store):
            raise RuntimeError("Mission store is unavailable")
        try:
            store = await require_store(auto_enable=True)
        except web.HTTPNotFound as exc:
            raise RuntimeError("Mission store is unavailable") from exc
        try:
            job = store.get_job(job_id)
        except KeyError:
            return None
        return {
            "id": str(getattr(job, "id", "") or ""),
            "status": str(getattr(job, "status", "") or ""),
            "result": getattr(job, "result", None) or {},
            "error": getattr(job, "error", None) or {},
            "updated_at": str(getattr(job, "updated_at", "") or ""),
        }

    async def cancel_mission(job_id: str) -> dict[str, Any]:
        require_store = view.get(APP_MISSION_REQUIRE_STORE)
        if not callable(require_store):
            raise RuntimeError("Mission store is unavailable")
        store = await require_store(auto_enable=True)
        try:
            store.get_job(job_id)
        except KeyError as exc:
            raise RuntimeError("Mission job is unavailable") from exc
        engine = view.get("autonomy_engine")
        if engine is None:
            raise RuntimeError("Mission runtime is unavailable; stop cannot be confirmed")
        job = await engine.cancel_job(job_id, actor="work")
        return {
            "id": str(getattr(job, "id", "") or ""),
            "status": str(getattr(job, "status", "") or ""),
            "updated_at": str(getattr(job, "updated_at", "") or ""),
        }

    return submit_to_mission, read_mission_status, cancel_mission


class _Work:
    name = "work"
    inject = ("web",)
    imports = (
        "thomas.server.routes.mission",
        "thomas.server.routes.mission_autonomy_runtime",
        "thomas.server.routes.mission_benchmark_routes",
        "thomas.server.routes.mission_control_routes",
        "thomas.server.routes.work",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Mission routes unavailable: missing API access guard")
            raise RuntimeError("mission has no access guard to register with")
        # Named here because the page keeps it open until it leaves, and one open page would hold the off switch.
        view = service.view(ctx, streams=("/api/mission/stream",))
        try:
            from thomas.server.app_keys import APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE
            from thomas.server.routes.mission import register_mission_routes

            register_mission_routes(
                view,
                web_dir=service.web_dir,
                require_api_access=service.require_api_access,
                run_store_enabled_key=APP_RUN_STORE_ENABLED,
                run_store_module_key=APP_RUN_STORE_MODULE,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Mission routes unavailable: %s", exc)
            raise
        try:
            from thomas.server.routes.work import register_work_routes

            submit, status, cancel = _bridge_to_mission(view)
            register_work_routes(
                view,
                require_api_access=service.require_api_access,
                mission_submitter=submit,
                mission_status_provider=status,
                mission_canceller=cancel,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Work routes unavailable: %s", exc)
            raise


plugin = _Work()
