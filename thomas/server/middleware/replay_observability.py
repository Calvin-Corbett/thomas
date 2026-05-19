# thomas/server/middleware/replay_observability.py
from __future__ import annotations

from aiohttp import web

from thomas.observability import auto_instrument
from thomas.observability.event_recorder import attach_run, end_run, record_event, start_run


@web.middleware
async def replay_observability_middleware(request: web.Request, handler):
    """
    Best-effort middleware that:
    - ensures an active run context for /api/chat and /api/autonomy (and any request that provides X-Thomas-Run-Id)
    - records request/response observability events
    - enables auto instrumentation for tool/model calls (best-effort, non-breaking)
    """
    # Install wrappers once (best-effort).
    try:
        auto_instrument.ensure_installed()
    except Exception:
        pass

    path = request.path or ""
    hdr_run = request.headers.get("X-Thomas-Run-Id") or request.headers.get("x-thomas-run-id")
    q_run = request.query.get("run_id")
    existing = hdr_run or q_run

    should_track = (
        existing is not None
        or path.startswith("/api/chat")
        or path.startswith("/api/autonomy")
        or path.startswith("/api/agent")
    )

    if not should_track:
        return await handler(request)

    run_id = existing or start_run(meta={"source": "http", "path": path, "method": request.method})

    attach_run(run_id)
    try:
        # record request (do not store raw body; only metadata)
        record_event(
            "http.request",
            {
                "method": request.method,
                "path": path,
                "query": dict(request.query),
                "remote": request.remote,
                "headers": {
                    k: v
                    for k, v in request.headers.items()
                    if k.lower() in {"user-agent", "content-type", "accept", "x-request-id", "x-thomas-run-id"}
                },
            },
        )

        resp = await handler(request)

        # record response metadata
        record_event(
            "http.response",
            {
                "status": getattr(resp, "status", None),
                "content_type": getattr(resp, "content_type", None),
            },
        )

        # make run_id discoverable by clients
        try:
            resp.headers["X-Thomas-Run-Id"] = run_id
        except Exception:
            pass

        end_run(ok=True)
        return resp
    except web.HTTPException as e:
        record_event("http.error", {"status": e.status, "reason": getattr(e, "reason", None)})
        end_run(ok=False, error=f"HTTP {e.status}")
        raise
    except Exception as e:
        record_event("http.error", {"error": str(e)})
        end_run(ok=False, error=str(e))
        raise
