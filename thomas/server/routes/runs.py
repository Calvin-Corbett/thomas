
"""aiohttp routes for Time-Travel Debugger (runs + replay + export)."""

from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aiohttp import web

from thomas.observability import run_store

RUNS_DB_PATH_KEY = web.AppKey("runs_db_path", str)
RUNS_CONFIG_KEY = web.AppKey("runs_config", object)


def resolve_db_path(config: Any) -> Path:
    root = _deep_get(config, ["memory", "root_path"])
    if not root:
        root = str(Path.cwd())
    return (Path(root) / ".thomas" / "runs.sqlite3").resolve()


def register_runs_routes(app: web.Application, config: Any) -> None:
    db_path = resolve_db_path(config)
    run_store.init_db(db_path)
    app[RUNS_DB_PATH_KEY] = str(db_path)
    app[RUNS_CONFIG_KEY] = config
    app.router.add_get("/api/runs", handle_list_runs)
    app.router.add_get("/api/runs/{run_id}", handle_get_run)
    app.router.add_get("/api/runs/{run_id}/replay", handle_replay_run)
    app.router.add_get("/api/runs/{run_id}/export", handle_export_run)


async def handle_list_runs(request: web.Request) -> web.Response:
    qp = request.rel_url.query
    limit = int(qp.get("limit", "50"))
    offset = int(qp.get("offset", "0"))
    filters: Dict[str, Any] = {}
    for key in ("session_id", "profile", "mode", "ok", "q"):
        v = qp.get(key)
        if v not in (None, ""):
            filters[key] = v
    runs = run_store.list_runs(limit=limit, offset=offset, filters=filters)
    return web.json_response({"runs": runs, "limit": limit, "offset": offset, "filters": filters})


async def handle_get_run(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    try:
        data = run_store.get_run(run_id)
    except KeyError:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")
    return web.json_response(data)


async def handle_replay_run(request: web.Request) -> web.StreamResponse:
    run_id = request.match_info["run_id"]
    try:
        run_store.get_run(run_id)
    except KeyError:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")

    resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson; charset=utf-8"})
    await resp.prepare(request)

    for obj in run_store.stream_replay(run_id):
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        await resp.write(line.encode("utf-8"))

    await resp.write_eof()
    return resp


async def handle_export_run(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    try:
        data = run_store.get_run(run_id)
    except KeyError:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")

    run_meta = data["run"]
    events_iter = list(run_store.stream_replay(run_id))

    debug_zip = io.BytesIO()
    with zipfile.ZipFile(debug_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("run.json", json.dumps(run_meta, indent=2, ensure_ascii=False))
        zf.writestr("events.ndjson", "\n".join(json.dumps(e, ensure_ascii=False) for e in events_iter) + "\n")
        zf.writestr("conversation.json", json.dumps(_reconstruct_conversation(events_iter), indent=2, ensure_ascii=False))
        zf.writestr("config_summary.json", json.dumps(_config_summary(request, run_meta), indent=2, ensure_ascii=False))
        zf.writestr("README.txt", _export_readme(request, run_meta))

    debug_zip.seek(0)
    fname = f"thomas_debug_pack_{run_id}.zip"
    return web.Response(
        body=debug_zip.getvalue(),
        headers={"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _reconstruct_conversation(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []
    for e in events:
        role = e.get("role")
        text = e.get("text") or e.get("content") or e.get("message")
        if isinstance(role, str) and isinstance(text, str) and text.strip():
            messages.append({"role": role, "content": text})
    return {"messages": messages, "note": "best-effort reconstruction from stored events (may be incomplete)"}


def _config_summary(request: web.Request, run_meta: Dict[str, Any]) -> Dict[str, Any]:
    cfg = request.app.get(RUNS_CONFIG_KEY)
    profiles = _deep_get(cfg, ["profiles"])
    out: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thomas_version": run_meta.get("thomas_version"),
        "run": {"profile": run_meta.get("profile"), "mode": run_meta.get("mode"), "model_id": run_meta.get("model_id")},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "runs_db_path": request.app.get(RUNS_DB_PATH_KEY),
    }
    if isinstance(profiles, dict):
        out["profiles"] = sorted(list(profiles.keys()))
    elif isinstance(profiles, list):
        out["profiles"] = profiles

    mem_root = _deep_get(cfg, ["memory", "root_path"])
    if mem_root:
        out["memory_root_path"] = str(mem_root)
    return out


def _export_readme(request: web.Request, run_meta: Dict[str, Any]) -> str:
    host = request.host
    run_id = run_meta.get("run_id")
    return "\n".join(
        [
            "Thomas Time-Travel Debugger: Debug Pack",
            "",
            f"Run ID: {run_id}",
            f"Started: {run_meta.get('started_at')}",
            f"Ended:   {run_meta.get('ended_at')}",
            f"OK:      {run_meta.get('ok')}",
            "",
            "Files:",
            "  - run.json: run metadata",
            "  - events.ndjson: full recorded NDJSON stream",
            "  - conversation.json: best-effort reconstructed conversation",
            "  - config_summary.json: whitelist-first environment/config summary",
            "  - README.txt: this file",
            "",
            "Replay:",
            f"  http://{host}/api/runs/{run_id}/replay",
            "",
            "UI demo:",
            "  Open the web UI → Runs → Replay (no model call happens).",
            "",
        ]
    )


def _deep_get(obj: Any, keys: List[str], default: Any = None) -> Any:
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            cur = getattr(cur, k, default)
    return cur
