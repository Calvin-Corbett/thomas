"""aiohttp route registration for spend / cost-tracking endpoints."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sqlite3
from collections.abc import Callable
from io import StringIO
from typing import Any

from aiohttp import web

from thomas.core.cost_tracker import get_cost_tracker
from thomas.core.runtime_profile import all_profiles, resolve_runtime_profile

log = logging.getLogger(__name__)

RequireAccessFn = Callable[[web.Request], None]


def _token_total(tokens: dict[str, Any] | None) -> int:
    if not isinstance(tokens, dict):
        return 0
    try:
        return max(0, int(tokens.get("total", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _current_runtime_profile() -> dict[str, Any]:
    economy = "optimal"
    autonomy = 3
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        runtime_prefs = PreferencesStore(get_db_path()).get(user_id="default", thread_id=None)
        advanced = getattr(runtime_prefs, "advanced", None)
        rt = getattr(advanced, "runtime", None)
        economy = str(getattr(rt, "default_token_economy", economy) or economy)
        autonomy = int(getattr(rt, "autonomy_level", autonomy) or autonomy)
    # The preferences store is sqlite behind an optional import: ImportError when
    # the module is absent, OSError/sqlite3.Error for the file and the query, and
    # TypeError/ValueError/AttributeError for a row that is not shaped like the
    # runtime prefs. Any of those means "use the defaults above".
    except (ImportError, OSError, sqlite3.Error, TypeError, ValueError, AttributeError):
        log.debug("Runtime profile: preferences unavailable; using defaults", exc_info=True)

    return resolve_runtime_profile(
        autonomy_level=autonomy,
        economy_level=economy,
    ).to_dict()


def _token_graph(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graph: list[dict[str, Any]] = []
    for row in rows:
        tokens = row.get("tokens") if isinstance(row, dict) else {}
        detail = row.get("by_model_detail") if isinstance(row, dict) else {}
        graph.append(
            {
                "date": str(row.get("date", "")),
                "total_tokens": _token_total(tokens if isinstance(tokens, dict) else None),
                "prompt_tokens": int((tokens or {}).get("prompt", row.get("prompt_tokens", 0)) or 0),
                "completion_tokens": int((tokens or {}).get("completion", row.get("completion_tokens", 0)) or 0),
                "call_count": int(row.get("call_count", row.get("calls", 0)) or 0),
                "model_count": len(detail) if isinstance(detail, dict) else int(row.get("model_count", 0) or 0),
                "usd": float(row.get("usd", 0.0) or 0.0),
            }
        )
    return graph


def _token_streak(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = 0
    last_active_date = ""
    for row in reversed(rows):
        total = _token_total(row.get("tokens") if isinstance(row, dict) else None)
        if total <= 0:
            if count:
                break
            continue
        count += 1
        if not last_active_date:
            last_active_date = str(row.get("date", ""))
    return {"count": count, "active": count > 0, "last_active_date": last_active_date}


def _token_high_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "daily_total_tokens": {"date": "", "tokens": 0},
            "daily_prompt_tokens": {"date": "", "tokens": 0},
            "daily_completion_tokens": {"date": "", "tokens": 0},
            "daily_calls": {"date": "", "calls": 0},
        }

    def _max_row(key: str) -> dict[str, Any]:
        return max(rows, key=lambda row: int(row.get(key, 0) or 0))

    total_row = _max_row("total_tokens")
    prompt_row = _max_row("prompt_tokens")
    completion_row = _max_row("completion_tokens")
    calls_row = max(rows, key=lambda row: int(row.get("call_count", row.get("calls", 0)) or 0))
    return {
        "daily_total_tokens": {"date": total_row.get("date", ""), "tokens": int(total_row.get("total_tokens", 0) or 0)},
        "daily_prompt_tokens": {
            "date": prompt_row.get("date", ""),
            "tokens": int(prompt_row.get("prompt_tokens", 0) or 0),
        },
        "daily_completion_tokens": {
            "date": completion_row.get("date", ""),
            "tokens": int(completion_row.get("completion_tokens", 0) or 0),
        },
        "daily_calls": {
            "date": calls_row.get("date", ""),
            "calls": int(calls_row.get("call_count", calls_row.get("calls", 0)) or 0),
        },
    }


def _progress_item(item_id: str, label: str, value: int, target: int) -> dict[str, Any]:
    safe_target = max(1, int(target or 1))
    safe_value = max(0, int(value or 0))
    return {
        "id": item_id,
        "label": label,
        "value": safe_value,
        "target": safe_target,
        "progress_pct": min(100, int((safe_value / safe_target) * 100)),
        "unlocked": safe_value >= safe_target,
    }


def _token_achievements(
    *,
    tokens: dict[str, Any],
    model_detail: dict[str, Any],
    streak: dict[str, Any],
) -> dict[str, Any]:
    total = _token_total(tokens)
    model_count = len(model_detail)
    streak_count = int(streak.get("count", 0) or 0)
    items = [
        _progress_item("first_tokens", "First tokens tracked", total, 1),
        _progress_item("ten_k_day", "10K-token day", total, 10_000),
        _progress_item("two_model_mix", "Two-model mix", model_count, 2),
        _progress_item("three_day_streak", "Three-day streak", streak_count, 3),
    ]
    return {
        "unlocked_count": sum(1 for item in items if item["unlocked"]),
        "items": items,
    }


def register_spend_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
) -> None:
    """Register /api/spend/* routes on *app*."""

    # ── GET /api/spend/today ──

    async def api_spend_today(request: web.Request) -> web.Response:
        require_api_access(request)
        ct = get_cost_tracker()
        history_rows = ct.by_day(days=30)
        tokens = ct.today_tokens()
        model_detail = ct.today_by_model_detail()
        streak = _token_streak(history_rows)
        return web.json_response(
            {
                "primary_metric": "tokens",
                "total_usd": float(ct.today_usd()),
                "by_model": ct.by_model(),
                "by_model_detail": model_detail,
                "call_count": int(ct.today_call_count()),
                "tokens": tokens,
                "graph": _token_graph(history_rows),
                "streak": streak,
                "high_scores": _token_high_scores(history_rows),
                "achievements": _token_achievements(tokens=tokens, model_detail=model_detail, streak=streak),
                "runtime_profile": _current_runtime_profile(),
            }
        )

    # ── GET /api/spend/session ──

    async def api_spend_session(request: web.Request) -> web.Response:
        require_api_access(request)
        ct = get_cost_tracker()
        history_rows = ct.by_day(days=30)
        tokens = ct.session_tokens()
        model_detail = ct.session_by_model_detail()
        streak = _token_streak(history_rows)
        return web.json_response(
            {
                "primary_metric": "tokens",
                "total_usd": float(ct.session_usd()),
                "by_model_detail": model_detail,
                "call_count": int(ct.session_call_count()),
                "tokens": tokens,
                "streak": streak,
                "high_scores": _token_high_scores(history_rows),
                "achievements": _token_achievements(tokens=tokens, model_detail=model_detail, streak=streak),
                "runtime_profile": _current_runtime_profile(),
            }
        )

    # ── POST /api/spend/session/reset ──

    async def api_spend_session_reset(request: web.Request) -> web.Response:
        require_api_access(request)
        ct = get_cost_tracker()
        ct.reset_session()
        return web.json_response({"ok": True})

    # ── GET /api/spend/history ──

    async def api_spend_history(request: web.Request) -> web.Response:
        require_api_access(request)
        raw = request.query.get("days", "7")
        try:
            days = int(raw)
        except (ValueError, TypeError):
            days = 7
        days = max(1, min(days, 365))

        ct = get_cost_tracker()
        rows = ct.by_day(days=days)
        return web.json_response(rows)

    # ── GET /api/spend/pricing ──

    async def api_spend_pricing(request: web.Request) -> web.Response:
        require_api_access(request)
        ct = get_cost_tracker()
        return web.json_response(
            {
                "primary_metric": "tokens",
                "usage_units": "tokens",
                "pricing": ct.pricing_table(),
                "runtime_profile": _current_runtime_profile(),
                "runtime_matrix": all_profiles(),
            }
        )

    # ── GET /api/spend/export.csv ──

    async def api_spend_export_csv(request: web.Request) -> web.Response:
        require_api_access(request)
        raw = request.query.get("days", "30")
        try:
            days = int(raw)
        except (ValueError, TypeError):
            days = 30
        days = max(1, min(days, 365))

        ct = get_cost_tracker()
        rows = ct.by_day(days=days)

        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "total_tokens", "prompt_tokens", "completion_tokens", "calls", "usd"])
        for r in rows:
            w.writerow(
                [
                    r["date"],
                    int(r.get("total_tokens", 0) or 0),
                    int(r.get("prompt_tokens", 0) or 0),
                    int(r.get("completion_tokens", 0) or 0),
                    int(r.get("call_count", r.get("calls", 0)) or 0),
                    f"{float(r['usd']):.10f}",
                ]
            )

        return web.Response(
            body=buf.getvalue(),
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="thomas_token_usage_{days}d.csv"',
            },
        )

    # ── GET /api/spend/stream  (SSE) ──

    async def api_spend_stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        ct = get_cost_tracker()
        sub = ct.subscribe()

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)

        try:
            await resp.write(b"event: hello\ndata: {}\n\n")
            while True:
                payload = await asyncio.to_thread(sub.get, 15.0)
                if payload is None:
                    await resp.write(b": keepalive\n\n")
                    continue
                data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                await resp.write(f"event: spend\ndata: {data}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            sub.close()
            ct.unsubscribe(sub)
            try:
                await resp.write_eof()
            except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
                pass

        return resp

    # ── GET /api/runtime/profile ──

    async def api_runtime_profile(request: web.Request) -> web.Response:
        """Return the current resolved runtime profile (autonomy × economy)."""
        require_api_access(request)
        return web.json_response(_current_runtime_profile())

    # ── GET /api/runtime/matrix ──

    async def api_runtime_matrix(request: web.Request) -> web.Response:
        """Return the full 4×3 autonomy × economy matrix for the UI."""
        require_api_access(request)
        return web.json_response({"profiles": all_profiles()})

    # ── register ──

    app.router.add_get("/api/spend/today", api_spend_today)
    app.router.add_get("/api/spend/session", api_spend_session)
    app.router.add_post("/api/spend/session/reset", api_spend_session_reset)
    app.router.add_get("/api/spend/history", api_spend_history)
    app.router.add_get("/api/spend/pricing", api_spend_pricing)
    app.router.add_get("/api/spend/export.csv", api_spend_export_csv)
    app.router.add_get("/api/spend/stream", api_spend_stream)
    app.router.add_get("/api/runtime/profile", api_runtime_profile)
    app.router.add_get("/api/runtime/matrix", api_runtime_matrix)
