# thomas/server/routes/replay_debugger.py
from __future__ import annotations

import asyncio
import json
from aiohttp import web
from importlib import resources

from thomas.observability.redaction import RedactionConfig, redact_obj
from thomas.observability.run_store_replay import (
    count_events,
    get_event_at_index,
    get_run_metadata,
    list_events,
)

def _parse_int(q: str | None, default: int) -> int:
    if q is None:
        return default
    try:
        return int(q)
    except Exception:
        return default

def _parse_float(q: str | None, default: float) -> float:
    if q is None:
        return default
    try:
        return float(q)
    except Exception:
        return default

async def handle_run_events(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    start = _parse_int(request.query.get("start"), 0)
    limit = _parse_int(request.query.get("limit"), 250)
    total = count_events(run_id)
    events = list_events(run_id, start=start, limit=limit)
    cfg = RedactionConfig.default()
    payload = {
        "run_id": run_id,
        "total": total,
        "start": start,
        "limit": limit,
        "events": [
            {
                "index": e.index,
                "seq": e.seq,
                "t_ms": e.t_ms,
                "event_type": e.event_type,
                "payload": redact_obj(e.payload, cfg),
            }
            for e in events
        ],
    }
    return web.json_response(payload)

async def handle_replay_seek(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    body = await request.json()
    index = int(body.get("index", 0))
    ev = get_event_at_index(run_id, index)
    if ev is None:
        return web.json_response({"ok": False, "error": "index_out_of_range"}, status=404)
    cfg = RedactionConfig.default()
    return web.json_response({"ok": True, "event": {
        "index": ev.index, "seq": ev.seq, "t_ms": ev.t_ms, "event_type": ev.event_type, "payload": redact_obj(ev.payload, cfg),
    }})

async def handle_replay_step(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    body = await request.json()
    index = int(body.get("index", 0))
    delta = int(body.get("delta", 1))
    new_index = index + delta
    ev = get_event_at_index(run_id, new_index)
    if ev is None:
        return web.json_response({"ok": False, "error": "index_out_of_range"}, status=404)
    cfg = RedactionConfig.default()
    return web.json_response({"ok": True, "event": {
        "index": ev.index, "seq": ev.seq, "t_ms": ev.t_ms, "event_type": ev.event_type, "payload": redact_obj(ev.payload, cfg),
    }})

async def handle_replay_stream(request: web.Request) -> web.StreamResponse:
    run_id = request.match_info["run_id"]
    start = _parse_int(request.query.get("from"), 0)
    speed = _parse_float(request.query.get("speed"), 1.0)
    limit = _parse_int(request.query.get("limit"), 0)
    if speed < 0:
        speed = 1.0

    cfg = RedactionConfig.default()
    resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson; charset=utf-8"})
    await resp.prepare(request)

    chunk = 500
    idx = start
    streamed = 0
    prev_t = None

    while True:
        if limit and streamed >= limit:
            break
        batch = list_events(run_id, start=idx, limit=min(chunk, (limit - streamed) if limit else chunk))
        if not batch:
            break
        for ev in batch:
            if limit and streamed >= limit:
                break
            if speed and speed > 0 and prev_t is not None and ev.t_ms is not None:
                dt_ms = max(0, (ev.t_ms - prev_t))
                if dt_ms:
                    await asyncio.sleep((dt_ms / 1000.0) / speed)
            prev_t = ev.t_ms if ev.t_ms is not None else prev_t
            line = json.dumps({
                "index": ev.index, "seq": ev.seq, "t_ms": ev.t_ms, "event_type": ev.event_type, "payload": redact_obj(ev.payload, cfg),
            }, separators=(",", ":")).encode("utf-8") + b"\n"
            await resp.write(line)
            streamed += 1
        idx += len(batch)

    await resp.write_eof()
    return resp

async def handle_run_export_json(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    meta = get_run_metadata(run_id) or {"run_id": run_id}
    total = count_events(run_id)
    max_events = _parse_int(request.query.get("max_events"), 20_000)
    if max_events < 0:
        max_events = 0
    cfg = RedactionConfig.default()

    events = []
    idx = 0
    remaining = min(total, max_events)
    while remaining > 0:
        batch = list_events(run_id, start=idx, limit=min(1000, remaining))
        if not batch:
            break
        for ev in batch:
            events.append({
                "index": ev.index, "seq": ev.seq, "t_ms": ev.t_ms, "event_type": ev.event_type, "payload": redact_obj(ev.payload, cfg),
            })
        idx += len(batch)
        remaining -= len(batch)

    payload = {
        "schema_version": 1,
        "feature_id": "observability.run_replay_debugger",
        "run": redact_obj(meta, cfg),
        "events": events,
        "truncated": total > max_events,
        "total_events": total,
    }
    return web.json_response(payload)

def _asset_path(rel: str):
    # Files live in thomas/server/web/...
    pkg = "thomas.server.web"
    return resources.files(pkg) / rel

async def handle_ui(request: web.Request) -> web.Response:
    p = _asset_path("replay_debugger.html")
    return web.FileResponse(path=str(p))

async def handle_css(request: web.Request) -> web.Response:
    p = _asset_path("css/replay_debugger.css")
    return web.FileResponse(path=str(p))

async def handle_js(request: web.Request) -> web.Response:
    p = _asset_path("js/replay_debugger.js")
    return web.FileResponse(path=str(p))

def setup(app: web.Application) -> None:
    # API
    app.router.add_get("/api/runs/{run_id}/events", handle_run_events)
    app.router.add_post("/api/runs/{run_id}/replay/seek", handle_replay_seek)
    app.router.add_post("/api/runs/{run_id}/replay/step", handle_replay_step)
    app.router.add_get("/api/runs/{run_id}/replay_stream", handle_replay_stream)
    app.router.add_get("/api/runs/{run_id}/export.json", handle_run_export_json)
    # UI + assets (self-contained, no reliance on static routes)
    app.router.add_get("/replay_debugger.html", handle_ui)
    app.router.add_get("/css/replay_debugger.css", handle_css)
    app.router.add_get("/js/replay_debugger.js", handle_js)
