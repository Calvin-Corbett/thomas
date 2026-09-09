from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
from typing import Any

from aiohttp import web

from .models import Job


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    return datetime.fromisoformat(val)


def _dt_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _job_to_json(j: Job) -> dict[str, Any]:
    return {
        "id": j.id,
        "name": j.name,
        "kind": j.kind,
        "status": j.status,
        "created_at": _dt_iso(j.created_at),
        "updated_at": _dt_iso(j.updated_at),
        "next_run_at": _dt_iso(j.next_run_at),
        "parent_id": j.parent_id,
        "session_id": j.session_id,
        "payload": j.payload,
        "result": j.result,
        "error": j.error,
        "schedule": j.schedule,
        "attempts": j.attempts,
        "retry_policy": {
            "max_attempts": j.retry_policy.max_attempts,
            "base_delay_s": j.retry_policy.base_delay_s,
            "max_delay_s": j.retry_policy.max_delay_s,
            "jitter": j.retry_policy.jitter,
            "backoff": j.retry_policy.backoff,
        },
        "risk_class": j.risk_class,
        "requires_approval": j.requires_approval,
        "approved": j.approved,
        "cancelled": j.cancelled,
    }


def _require_token_middleware(api_token: str):
    @web.middleware
    async def _mw(request: web.Request, handler):
        auth = request.headers.get("Authorization", "")
        x = request.headers.get("X-Api-Token", "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        elif x:
            token = x.strip()
        if token != api_token:
            raise web.HTTPUnauthorized(text="missing or invalid token")
        return await handler(request)

    return _mw


def register_autonomy_routes(
    app: web.Application,
    *,
    engine,
    store,
    policy,
    route_prefix: str = "/api/autonomy",
    api_token: str | None = None,
    serve_ui: bool = True,
) -> None:
    """Register Autonomy API + UI routes on an aiohttp app."""

    middlewares = []
    if api_token:
        middlewares.append(_require_token_middleware(api_token))

    api_app = web.Application(middlewares=middlewares)

    async def status(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "engine": {"running": engine.is_running, "worker_id": engine.worker_id},
                "policy": policy.to_json(),
            }
        )

    async def wakeup(request: web.Request) -> web.Response:
        engine.wake_up()
        return web.json_response({"ok": True})

    async def list_jobs(request: web.Request) -> web.Response:
        q = request.query
        jobs = store.list_jobs(
            status=q.get("status") or None,
            kind=q.get("kind") or None,
            parent_id=q.get("parent_id") or None,
            session_id=q.get("session_id") or None,
            limit=int(q.get("limit", "200")),
            offset=int(q.get("offset", "0")),
        )
        return web.json_response({"jobs": [_job_to_json(j) for j in jobs]})

    async def create_job(request: web.Request) -> web.Response:
        data = await request.json()
        name = str(data.get("name") or "").strip() or "Job"
        kind = str(data.get("kind") or "").strip()
        if not kind:
            raise web.HTTPBadRequest(text="kind required")

        payload = data.get("payload") or {}
        schedule = data.get("schedule") or None
        run_at = _parse_dt(data.get("run_at"))
        risk_class = str(data.get("risk_class") or "low")
        requires_approval = bool(data.get("requires_approval") or False)
        parent_id = data.get("parent_id") or None
        session_id = data.get("session_id") or None

        job = store.create_job(
            name=name,
            kind=kind,
            payload=payload,
            schedule=schedule,
            next_run_at=run_at,
            risk_class=risk_class,
            requires_approval=requires_approval,
            parent_id=parent_id,
            session_id=session_id,
        )
        engine.wake_up()
        return web.json_response({"job": _job_to_json(job)})

    async def cancel_job(request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        store.cancel_job(job_id, actor="user")
        engine.wake_up()
        return web.json_response({"ok": True})

    async def run_now(request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        store.set_job_status(job_id, "queued", next_run_at=datetime.now(timezone.utc), lock_clear=True)
        engine.wake_up()
        return web.json_response({"ok": True})

    async def requeue_job(request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        store.set_job_status(
            job_id,
            "queued",
            error=None,
            result=None,
            attempts=0,
            next_run_at=datetime.now(timezone.utc),
            lock_clear=True,
        )
        engine.wake_up()
        return web.json_response({"ok": True})

    async def list_approvals(request: web.Request) -> web.Response:
        q = request.query
        aps = store.list_approvals(status=q.get("status") or None, limit=int(q.get("limit", "200")))
        out = []
        for a in aps:
            out.append(
                {
                    "id": a.id,
                    "job_id": a.job_id,
                    "action": a.action,
                    "risk_class": a.risk_class,
                    "status": a.status,
                    "requested_at": _dt_iso(a.requested_at),
                    "decided_at": _dt_iso(a.decided_at),
                    "decided_by": a.decided_by,
                    "decision_reason": a.decision_reason,
                }
            )
        return web.json_response({"approvals": out})

    async def decide_approval(request: web.Request) -> web.Response:
        approval_id = request.match_info["approval_id"]
        data = await request.json()
        approve = bool(data.get("approve"))
        actor = str(data.get("actor") or "user")
        reason = data.get("reason")

        ap = store.decide_approval(approval_id=approval_id, approve=approve, actor=actor, reason=reason)
        if approve:
            store.set_job_status(
                ap.job_id,
                "queued",
                approved=True,
                requires_approval=False,
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        else:
            store.cancel_job(ap.job_id, actor=actor)

        engine.wake_up()
        return web.json_response({"id": ap.id, "job_id": ap.job_id, "status": ap.status})

    async def list_audit(request: web.Request) -> web.Response:
        q = request.query
        events = store.list_audit(job_id=q.get("job_id") or None, limit=int(q.get("limit", "400")))
        out = []
        for e in events:
            out.append(
                {
                    "id": e.id,
                    "job_id": e.job_id,
                    "ts": _dt_iso(e.ts),
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "detail": e.detail,
                    "prev_sig": e.prev_sig,
                    "sig": e.sig,
                }
            )
        return web.json_response({"events": out})

    async def list_messages(request: web.Request) -> web.Response:
        q = request.query
        msgs = store.list_messages(limit=int(q.get("limit", "200")), session_id=q.get("session_id") or None)
        return web.json_response({"messages": msgs})

    async def list_briefings(request: web.Request) -> web.Response:
        q = request.query
        items = store.list_briefings(limit=int(q.get("limit", "30")))
        return web.json_response({"briefings": items})

    api_app.router.add_get("/status", status)
    api_app.router.add_post("/wakeup", wakeup)
    api_app.router.add_get("/jobs", list_jobs)
    api_app.router.add_post("/jobs", create_job)
    api_app.router.add_post("/jobs/{job_id}/cancel", cancel_job)
    api_app.router.add_post("/jobs/{job_id}/run_now", run_now)
    api_app.router.add_post("/jobs/{job_id}/requeue", requeue_job)
    api_app.router.add_get("/approvals", list_approvals)
    api_app.router.add_post("/approvals/{approval_id}/decision", decide_approval)
    # Back-compat for early UI builds
    api_app.router.add_post("/approvals/{approval_id}/decide", decide_approval)
    api_app.router.add_get("/audit", list_audit)
    api_app.router.add_get("/messages", list_messages)
    api_app.router.add_get("/briefings", list_briefings)

    app.add_subapp(route_prefix, api_app)

    if not serve_ui:
        return

    # UI assets served from package resources
    ui_pkg = "thomas.marketplace.autonomy.ui"
    asset_map = {
        "autonomy.html": "text/html; charset=utf-8",
        "autonomy.js": "application/javascript; charset=utf-8",
        "autonomy.css": "text/css; charset=utf-8",
    }

    async def ui_redirect(request: web.Request) -> web.Response:
        raise web.HTTPFound("/autonomy.html")

    async def serve_asset(request: web.Request, name: str) -> web.Response:
        if name not in asset_map:
            raise web.HTTPNotFound()
        data = resources.files(ui_pkg).joinpath(name).read_bytes()
        # aiohttp sets content_type + charset separately; we keep it simple:
        ct = asset_map[name].split(";")[0]
        return web.Response(body=data, content_type=ct, charset="utf-8")

    async def ui_html(request: web.Request) -> web.Response:
        return await serve_asset(request, "autonomy.html")

    async def ui_js(request: web.Request) -> web.Response:
        return await serve_asset(request, "autonomy.js")

    async def ui_css(request: web.Request) -> web.Response:
        return await serve_asset(request, "autonomy.css")

    app.router.add_get("/autonomy", ui_redirect)
    app.router.add_get("/autonomy.html", ui_html)
    app.router.add_get("/autonomy.js", ui_js)
    app.router.add_get("/autonomy.css", ui_css)
