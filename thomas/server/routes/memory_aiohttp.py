"""Memory and memory-governance aiohttp route registration."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiohttp import web

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


def _resolve_app_memory(app: web.Application) -> Any:
    for key, value in app.items():
        key_name = str(getattr(key, "name", "") or getattr(key, "_name", "") or "")
        if key_name == "memory" or key_name.endswith(".memory"):
            return value
    return app.get("memory")


def register_memory_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_memory(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response({"enabled": False, "error": "memory engine unavailable"})

        sid = str(request.query.get("session_id") or "").strip() or None
        try:
            trace_limit = int(request.query.get("trace_limit", "8"))
        except Exception:
            trace_limit = 8
        trace_limit = max(1, min(50, trace_limit))

        try:
            data = mem.diagnostics(thread=sid, trace_limit=trace_limit)
        except Exception as e:
            return web.json_response({"enabled": False, "error": str(e)}, status=500)

        return web.json_response(
            {
                "enabled": True,
                "thread": sid,
                **data,
            }
        )

    async def api_memory_pin_set(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response({"ok": False, "error": "memory engine unavailable"}, status=503)

        payload = await read_json(request)
        key = str(payload.get("key") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not key:
            raise web.HTTPBadRequest(text="missing key")
        if not text:
            raise web.HTTPBadRequest(text="missing text")

        mem.pin(key, text)
        return web.json_response({"ok": True, "key": key})

    async def api_memory_pin_clear(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response({"ok": False, "error": "memory engine unavailable"}, status=503)

        key = str(request.match_info.get("key") or "").strip()
        if not key:
            raise web.HTTPBadRequest(text="missing key")
        mem.unpin(key)
        return web.json_response({"ok": True, "key": key})

    async def api_memory_contradictions(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )

        raw_only_open = str(request.query.get("only_open", "1")).strip().lower()
        only_open = raw_only_open not in ("0", "false", "no", "off")
        try:
            limit = int(request.query.get("limit", "50"))
        except Exception:
            limit = 50
        limit = max(1, min(500, limit))

        list_fn = getattr(mem, "list_contradictions", None)
        if not callable(list_fn):
            return web.json_response(
                {
                    "ok": False,
                    "error": "contradiction API unavailable for current memory backend",
                },
                status=501,
            )

        try:
            rows = list_fn(only_open=only_open, limit=limit)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

        return web.json_response(
            {
                "ok": True,
                "only_open": only_open,
                "count": len(rows) if isinstance(rows, list) else 0,
                "contradictions": rows if isinstance(rows, list) else [],
            }
        )

    async def api_memory_contradiction_resolve(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )

        cid_raw = str(request.match_info.get("cid") or "").strip()
        if not cid_raw:
            raise web.HTTPBadRequest(text="missing contradiction id")
        try:
            cid = int(cid_raw)
        except Exception:
            raise web.HTTPBadRequest(text="invalid contradiction id")
        if cid <= 0:
            raise web.HTTPBadRequest(text="invalid contradiction id")

        resolved = True
        try:
            payload = await read_json(request)
        except web.HTTPBadRequest:
            payload = {}
        if isinstance(payload, dict) and "resolved" in payload:
            resolved = bool(payload.get("resolved"))

        resolve_fn = getattr(mem, "resolve_contradiction", None)
        if not callable(resolve_fn):
            return web.json_response(
                {
                    "ok": False,
                    "error": "contradiction API unavailable for current memory backend",
                },
                status=501,
            )

        try:
            ok = bool(resolve_fn(cid, resolved=resolved))
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        if not ok:
            return web.json_response(
                {"ok": False, "error": "failed to update contradiction"},
                status=500,
            )
        return web.json_response({"ok": True, "id": cid, "resolved": bool(resolved)})

    async def api_memory_contradictions_review(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )
        try:
            limit = int(request.query.get("limit", "50"))
        except Exception:
            limit = 50
        limit = max(1, min(500, limit))
        status = str(request.query.get("status") or "").strip() or None
        severity = str(request.query.get("severity") or "").strip() or None
        route = str(request.query.get("route") or "").strip() or None

        list_fn = getattr(mem, "list_contradictions_review", None)
        if not callable(list_fn):
            return web.json_response(
                {"ok": False, "error": "contradiction review API unavailable"},
                status=501,
            )
        try:
            rows = list_fn(status=status, severity=severity, route=route, limit=limit)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        return web.json_response(
            {
                "ok": True,
                "count": len(rows) if isinstance(rows, list) else 0,
                "status": status,
                "severity": severity,
                "route": route,
                "contradictions": rows if isinstance(rows, list) else [],
            }
        )

    async def api_memory_contradiction_review_decide(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )

        cid_raw = str(request.match_info.get("cid") or "").strip()
        if not cid_raw:
            raise web.HTTPBadRequest(text="missing contradiction id")
        try:
            cid = int(cid_raw)
        except Exception:
            raise web.HTTPBadRequest(text="invalid contradiction id")
        if cid <= 0:
            raise web.HTTPBadRequest(text="invalid contradiction id")

        payload = await read_json(request)
        decision = str(payload.get("decision") or "").strip().lower()
        if not decision:
            if "approve" in payload:
                decision = "approve" if bool(payload.get("approve")) else "dismiss"
            elif "resolved" in payload:
                decision = "approve" if bool(payload.get("resolved")) else "reopen"
        if not decision:
            raise web.HTTPBadRequest(text="missing review decision")
        actor = str(payload.get("actor") or "api").strip() or "api"
        reason = str(payload.get("reason") or "").strip()

        decide_fn = getattr(mem, "decide_contradiction_review", None)
        if callable(decide_fn):
            try:
                ok = bool(decide_fn(cid, decision=decision, actor=actor, reason=reason))
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)}, status=500)
        else:
            resolve_fn = getattr(mem, "resolve_contradiction", None)
            if not callable(resolve_fn):
                return web.json_response(
                    {"ok": False, "error": "contradiction review API unavailable"},
                    status=501,
                )
            try:
                resolved = decision in ("approve", "resolve", "dismiss", "reject")
                ok = bool(resolve_fn(cid, resolved=resolved))
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        if not ok:
            return web.json_response(
                {"ok": False, "error": "failed to decide contradiction review"},
                status=500,
            )
        return web.json_response(
            {
                "ok": True,
                "id": cid,
                "decision": decision,
                "actor": actor,
            }
        )

    async def api_memory_curator_approvals(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )
        status = str(request.query.get("status") or "pending").strip()
        try:
            limit = int(request.query.get("limit", "100"))
        except Exception:
            limit = 100
        limit = max(1, min(1000, limit))
        list_fn = getattr(mem, "list_curator_approvals", None)
        if not callable(list_fn):
            return web.json_response(
                {"ok": False, "error": "curator approval API unavailable"},
                status=501,
            )
        try:
            rows = list_fn(status=status, limit=limit)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        return web.json_response(
            {
                "ok": True,
                "status": status,
                "count": len(rows) if isinstance(rows, list) else 0,
                "approvals": rows if isinstance(rows, list) else [],
            }
        )

    async def api_memory_curator_approval_decide(request: web.Request) -> web.Response:
        require_api_access(request)
        mem = _resolve_app_memory(request.app)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )
        aid_raw = str(request.match_info.get("aid") or "").strip()
        if not aid_raw:
            raise web.HTTPBadRequest(text="missing approval id")
        try:
            aid = int(aid_raw)
        except Exception:
            raise web.HTTPBadRequest(text="invalid approval id")
        if aid <= 0:
            raise web.HTTPBadRequest(text="invalid approval id")

        payload = await read_json(request)
        if "approve" not in payload:
            raise web.HTTPBadRequest(text="missing approve flag")
        approve = bool(payload.get("approve"))
        actor = str(payload.get("actor") or "api").strip() or "api"
        reason = str(payload.get("reason") or "").strip()

        decide_fn = getattr(mem, "decide_curator_approval", None)
        if not callable(decide_fn):
            return web.json_response(
                {"ok": False, "error": "curator approval API unavailable"},
                status=501,
            )
        try:
            out = dict(decide_fn(aid, approve=approve, actor=actor, reason=reason))
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        if not bool(out.get("ok", False)):
            err = str(out.get("error") or "failed")
            status_code = 404 if err == "not_found" else 500
            return web.json_response({"ok": False, "error": err}, status=status_code)
        return web.json_response(out)

    app.router.add_get("/api/memory", api_memory)
    app.router.add_post("/api/memory/pins", api_memory_pin_set)
    app.router.add_delete("/api/memory/pins/{key}", api_memory_pin_clear)
    app.router.add_get("/api/memory/contradictions", api_memory_contradictions)
    app.router.add_post(
        "/api/memory/contradictions/{cid}/resolve",
        api_memory_contradiction_resolve,
    )
    app.router.add_get("/api/memory/contradictions/review", api_memory_contradictions_review)
    app.router.add_post(
        "/api/memory/contradictions/{cid}/review",
        api_memory_contradiction_review_decide,
    )
    app.router.add_get("/api/memory/curator/approvals", api_memory_curator_approvals)
    app.router.add_post(
        "/api/memory/curator/approvals/{aid}/decision",
        api_memory_curator_approval_decide,
    )
