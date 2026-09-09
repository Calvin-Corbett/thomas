"""aiohttp routes for Time-Travel Debugger (runs + replay + export)."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import io
import ipaddress
import json
import logging
import platform
import sqlite3
import sys
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import resolve_thomas_data_dir
from thomas.observability import run_store
from thomas.observability.redaction import RedactionConfig, redact_obj

_log = logging.getLogger(__name__)

RUNS_DB_PATH_KEY = web.AppKey("runs_db_path", str)
RUNS_CONFIG_KEY = web.AppKey("runs_config", object)
_EVENT_PAGE_LIMIT_MAX = 5000
_EVENT_PAGE_LIMIT_DEFAULT = 250
_STREAM_CHUNK = 500


def resolve_db_path(config: Any) -> Path:
    root = _deep_get(config, ["memory", "root_path"])
    if not root:
        root = str(resolve_thomas_data_dir())
    return (Path(root) / ".thomas" / "runs.sqlite3").resolve()


def register_runs_routes(app: web.Application, config: Any) -> None:
    db_path = resolve_db_path(config)
    run_store.init_db(db_path)
    app[RUNS_DB_PATH_KEY] = str(db_path)
    app[RUNS_CONFIG_KEY] = config
    app.router.add_get("/api/runs", handle_list_runs)
    app.router.add_get("/api/runs/{run_id}", handle_get_run)
    app.router.add_get("/api/runs/{run_id}/replay", handle_replay_run)
    app.router.add_get("/api/runs/{run_id}/events", handle_run_events)
    app.router.add_post("/api/runs/{run_id}/replay/seek", handle_replay_seek)
    app.router.add_post("/api/runs/{run_id}/replay/step", handle_replay_step)
    app.router.add_get("/api/runs/{run_id}/replay_stream", handle_replay_stream)
    app.router.add_get("/api/runs/{run_id}/export", handle_export_run)
    app.router.add_get("/api/runs/{run_id}/export.json", handle_export_run_json)
    app.router.add_post("/api/runs/{run_id}/cancel", handle_cancel_run)


def _extract_request_token(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Api-Token") or "").strip()


def _is_loopback_host(host: str) -> bool:
    h = str(host or "").strip().lower()
    if not h:
        return False
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return bool(ipaddress.ip_address(h).is_loopback)
    except ValueError:
        return False


def _is_loopback_request(request: web.Request) -> bool:
    try:
        peer = request.transport.get_extra_info("peername") if request.transport else None
    except Exception:
        peer = None
    if peer and isinstance(peer, (tuple, list)) and peer:
        return _is_loopback_host(str(peer[0]))
    return _is_loopback_host(str(request.remote or ""))


def _require_runs_access(request: web.Request) -> None:
    cfg = request.app.get(RUNS_CONFIG_KEY)
    mode = str(getattr(getattr(cfg, "server", None), "access_mode", "local") or "local").strip().lower()
    if mode == "remote":
        expected = str(getattr(getattr(cfg, "server", None), "api_token", "") or "").strip()
        if not expected:
            raise web.HTTPUnauthorized(text="server api token is not configured")
        incoming = _extract_request_token(request)
        if not incoming:
            raise web.HTTPUnauthorized(text="missing api token")
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(text="invalid api token")
        return
    if not _is_loopback_request(request):
        raise web.HTTPForbidden(text="This endpoint is only available from localhost.")


async def handle_list_runs(request: web.Request) -> web.Response:
    _require_runs_access(request)
    qp = request.rel_url.query
    limit = _read_query_int(qp, "limit", default=50, min_value=1, max_value=500)
    offset = _read_query_int(qp, "offset", default=0, min_value=0, max_value=100000)
    filters: dict[str, Any] = {}
    for key in ("session_id", "profile", "mode", "ok", "q"):
        v = qp.get(key)
        if v not in (None, ""):
            filters[key] = v
    runs = run_store.list_runs(limit=limit, offset=offset, filters=filters)
    return web.json_response({"runs": runs, "limit": limit, "offset": offset, "filters": filters})


async def handle_get_run(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    try:
        data = run_store.get_run(run_id)
    except KeyError:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")
    return web.json_response(data)


async def handle_cancel_run(request: web.Request) -> web.Response:
    """Idempotent cancel signal for a run.

    Always returns 200 once auth passes: cancel is a soft signal — if the run
    doesn't exist or is already complete, there's nothing to do but acknowledge.
    """
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    return web.json_response({"ok": True, "run_id": run_id, "cancelled": True})


async def handle_replay_run(request: web.Request) -> web.StreamResponse:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    _ensure_run_exists(request, run_id)
    redaction_cfg = RedactionConfig.default()

    resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson; charset=utf-8"})
    await resp.prepare(request)

    for obj in run_store.stream_replay(run_id):
        line = json.dumps(redact_obj(obj, redaction_cfg), ensure_ascii=False, separators=(",", ":")) + "\n"
        await resp.write(line.encode("utf-8"))

    await resp.write_eof()
    return resp


async def handle_run_events(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    _ensure_run_exists(request, run_id)
    start = max(0, _parse_int(request.query.get("start"), 0))
    limit = _clamp_limit(_parse_int(request.query.get("limit"), _EVENT_PAGE_LIMIT_DEFAULT))
    total, events = _fetch_events_page(request, run_id, start=start, limit=limit)
    redaction_cfg = RedactionConfig.default()
    payload = {
        "run_id": run_id,
        "total": total,
        "start": start,
        "limit": limit,
        "events": [
            {
                "index": int(e.get("index") or 0),
                "seq": int(e.get("seq") or 0),
                "t_ms": e.get("t_ms"),
                "event_type": str(e.get("event_type") or ""),
                "payload": redact_obj(e.get("payload"), redaction_cfg),
            }
            for e in events
        ],
    }
    return web.json_response(payload)


async def handle_replay_seek(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    _ensure_run_exists(request, run_id)
    body = await _read_json_body(request)
    index = max(0, _parse_int(body.get("index"), 0))
    event = _event_at_index(request, run_id, index)
    if event is None:
        return web.json_response({"ok": False, "error": "index_out_of_range"}, status=404)
    redaction_cfg = RedactionConfig.default()
    return web.json_response({"ok": True, "event": _redacted_event(event, redaction_cfg)})


async def handle_replay_step(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    _ensure_run_exists(request, run_id)
    body = await _read_json_body(request)
    index = _parse_int(body.get("index"), 0)
    delta = _parse_int(body.get("delta"), 1)
    new_index = max(0, index + delta)
    event = _event_at_index(request, run_id, new_index)
    if event is None:
        return web.json_response({"ok": False, "error": "index_out_of_range"}, status=404)
    redaction_cfg = RedactionConfig.default()
    return web.json_response({"ok": True, "event": _redacted_event(event, redaction_cfg)})


async def handle_replay_stream(request: web.Request) -> web.StreamResponse:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    _ensure_run_exists(request, run_id)
    start = max(0, _parse_int(request.query.get("from"), 0))
    speed = _parse_float(request.query.get("speed"), 1.0)
    if speed < 0:
        speed = 1.0
    limit = max(0, _parse_int(request.query.get("limit"), 0))
    redaction_cfg = RedactionConfig.default()

    resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson; charset=utf-8"})
    await resp.prepare(request)

    idx = start
    streamed = 0
    prev_t_ms: int | None = None
    while True:
        if limit and streamed >= limit:
            break
        remaining = (limit - streamed) if limit else _STREAM_CHUNK
        page_limit = _clamp_limit(min(_STREAM_CHUNK, remaining))
        _total, events = _fetch_events_page(request, run_id, start=idx, limit=page_limit)
        if not events:
            break
        for event in events:
            if limit and streamed >= limit:
                break
            cur_t_ms = event.get("t_ms")
            try:
                cur_t_val = int(cur_t_ms) if cur_t_ms is not None else None
            except Exception:
                cur_t_val = None
            if speed > 0 and prev_t_ms is not None and cur_t_val is not None:
                dt_ms = max(0, cur_t_val - prev_t_ms)
                if dt_ms:
                    await asyncio.sleep((float(dt_ms) / 1000.0) / speed)
            if cur_t_val is not None:
                prev_t_ms = cur_t_val
            safe_event = _redacted_event(event, redaction_cfg)
            line = json.dumps(safe_event, ensure_ascii=False, separators=(",", ":")) + "\n"
            await resp.write(line.encode("utf-8"))
            streamed += 1
        idx += len(events)

    await resp.write_eof()
    return resp


async def handle_export_run(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    try:
        data = run_store.get_run(run_id)
    except KeyError:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")

    redaction_cfg = RedactionConfig.default()
    run_meta = redact_obj(data["run"], redaction_cfg)
    events_iter = [redact_obj(event, redaction_cfg) for event in run_store.stream_replay(run_id)]

    debug_zip = io.BytesIO()
    with zipfile.ZipFile(debug_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("run.json", json.dumps(run_meta, indent=2, ensure_ascii=False))
        zf.writestr("events.ndjson", "\n".join(json.dumps(e, ensure_ascii=False) for e in events_iter) + "\n")
        zf.writestr(
            "conversation.json", json.dumps(_reconstruct_conversation(events_iter), indent=2, ensure_ascii=False)
        )
        zf.writestr("config_summary.json", json.dumps(_config_summary(request, run_meta), indent=2, ensure_ascii=False))
        zf.writestr("README.txt", _export_readme(request, run_meta))

    debug_zip.seek(0)
    fname = f"thomas_debug_pack_{run_id}.zip"
    return web.Response(
        body=debug_zip.getvalue(),
        headers={"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{fname}"'},
    )


async def handle_export_run_json(request: web.Request) -> web.Response:
    _require_runs_access(request)
    run_id = request.match_info["run_id"]
    run_meta = _run_meta_row(request, run_id)
    if run_meta is None:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")
    redaction_cfg = RedactionConfig.default()
    max_events = max(0, _parse_int(request.query.get("max_events"), 20_000))

    total = _count_events(request, run_id)
    events: list[dict[str, Any]] = []
    idx = 0
    remaining = min(total, max_events)
    while remaining > 0:
        page_limit = _clamp_limit(min(1000, remaining))
        _total, batch = _fetch_events_page(request, run_id, start=idx, limit=page_limit)
        if not batch:
            break
        for event in batch:
            events.append(_redacted_event(event, redaction_cfg))
        idx += len(batch)
        remaining -= len(batch)

    payload = {
        "schema_version": 1,
        "feature_id": "observability.run_replay",
        "run": redact_obj(run_meta, redaction_cfg),
        "events": events,
        "total_events": total,
        "truncated": bool(total > max_events),
    }
    return web.json_response(payload)


def _reconstruct_conversation(events: list[dict[str, Any]]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for e in events:
        role = e.get("role")
        text = e.get("text") or e.get("content") or e.get("message")
        if isinstance(role, str) and isinstance(text, str) and text.strip():
            messages.append({"role": role, "content": text})
    return {"messages": messages, "note": "best-effort reconstruction from stored events (may be incomplete)"}


def _config_summary(request: web.Request, run_meta: dict[str, Any]) -> dict[str, Any]:
    cfg = request.app.get(RUNS_CONFIG_KEY)
    profiles = _deep_get(cfg, ["profiles"])
    out: dict[str, Any] = {
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


def _export_readme(request: web.Request, run_meta: dict[str, Any]) -> str:
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
            "  Open the web UI -> Runs -> Replay (no model call happens).",
            "",
        ]
    )


@contextlib.contextmanager
def _connect_db(request: web.Request) -> Iterator[sqlite3.Connection]:
    db_path = str(request.app.get(RUNS_DB_PATH_KEY) or "").strip()
    if not db_path:
        raise RuntimeError("runs db path unavailable")
    conn = sqlite3.connect(db_path, timeout=8, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _ensure_run_exists(request: web.Request, run_id: str) -> None:
    with _connect_db(request) as conn:
        row = conn.execute("SELECT 1 FROM runs WHERE run_id = ? LIMIT 1", (run_id,)).fetchone()
        if row is None:
            raise web.HTTPNotFound(text=f"run not found: {run_id}")


def _count_events(request: web.Request, run_id: str) -> int:
    with _connect_db(request) as conn:
        row = conn.execute("SELECT COUNT(1) AS n FROM events WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return 0
    try:
        return int(row["n"] or 0)
    except Exception:
        return 0


def _decode_payload(raw: Any) -> Any:
    if raw in (None, ""):
        return {}
    try:
        return json.loads(str(raw))
    except Exception:
        return {"_parse_error": True, "raw": str(raw)}


def _fetch_events_page(
    request: web.Request, run_id: str, *, start: int, limit: int
) -> tuple[int, list[dict[str, Any]]]:
    start = max(0, int(start))
    limit = _clamp_limit(limit)
    with _connect_db(request) as conn:
        total_row = conn.execute("SELECT COUNT(1) AS n FROM events WHERE run_id = ?", (run_id,)).fetchone()
        rows = conn.execute(
            """
            SELECT id, t_ms, seq, event_type, payload_json
            FROM events
            WHERE run_id = ?
            ORDER BY seq ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (run_id, int(limit), int(start)),
        ).fetchall()
    if total_row is None:
        total = 0
    else:
        try:
            total = int(total_row["n"] or 0)
        except Exception:
            total = 0
    events: list[dict[str, Any]] = []
    idx = start
    for row in rows:
        t_ms = row["t_ms"]
        seq = row["seq"]
        try:
            t_ms_val = None if t_ms is None else int(t_ms)
        except Exception:
            t_ms_val = None
        try:
            seq_val = int(seq) if seq is not None else idx
        except Exception:
            seq_val = idx
        events.append(
            {
                "index": idx,
                "seq": seq_val,
                "t_ms": t_ms_val,
                "event_type": str(row["event_type"] or ""),
                "payload": _decode_payload(row["payload_json"]),
            }
        )
        idx += 1
    return total, events


def _event_at_index(request: web.Request, run_id: str, index: int) -> dict[str, Any] | None:
    _total, events = _fetch_events_page(request, run_id, start=max(0, index), limit=1)
    if not events:
        return None
    return events[0]


def _run_meta_row(request: web.Request, run_id: str) -> dict[str, Any] | None:
    with _connect_db(request) as conn:
        row = conn.execute(
            """
            SELECT run_id, session_id, started_at, ended_at, profile, model_id, mode, ok, error,
                   iterations, tool_calls, usage_json, thomas_version
            FROM runs
            WHERE run_id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    usage = _decode_payload(row["usage_json"]) if row["usage_json"] not in (None, "") else None
    return {
        "run_id": row["run_id"],
        "session_id": row["session_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "profile": row["profile"],
        "model_id": row["model_id"],
        "mode": row["mode"],
        "ok": None if row["ok"] is None else bool(row["ok"]),
        "error": row["error"],
        "iterations": row["iterations"],
        "tool_calls": row["tool_calls"],
        "usage": usage,
        "thomas_version": row["thomas_version"],
    }


def _redacted_event(event: dict[str, Any], cfg: RedactionConfig) -> dict[str, Any]:
    return {
        "index": int(event.get("index") or 0),
        "seq": int(event.get("seq") or 0),
        "t_ms": event.get("t_ms"),
        "event_type": str(event.get("event_type") or ""),
        "payload": redact_obj(event.get("payload"), cfg),
    }


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp_limit(limit: int) -> int:
    val = max(1, int(limit))
    return min(_EVENT_PAGE_LIMIT_MAX, val)


def _read_query_int(
    query: Any,
    key: str,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    raw = query.get(key)
    if raw in (None, ""):
        return int(default)
    try:
        value = int(raw)
    except Exception as exc:
        raise web.HTTPBadRequest(text=f"{key} must be an integer") from exc
    if value < int(min_value) or value > int(max_value):
        raise web.HTTPBadRequest(text=f"{key} must be between {int(min_value)} and {int(max_value)}")
    return value


async def _read_json_body(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as e:
        _log.debug("runs: invalid json body: %s", type(e).__name__)
        raise web.HTTPBadRequest(text="invalid json body") from e
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


def _deep_get(obj: Any, keys: list[str], default: Any = None) -> Any:
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            cur = getattr(cur, k, default)
    return cur
