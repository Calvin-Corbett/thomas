"""aiohttp route registration for spend / cost-tracking endpoints."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Callable
from io import StringIO

from aiohttp import web

from thomas.core.cost_tracker import get_cost_tracker
from thomas.core.runtime_profile import all_profiles, resolve_runtime_profile

RequireAccessFn = Callable[[web.Request], None]


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
        return web.json_response(
            {
                "total_usd": float(ct.today_usd()),
                "by_model": ct.by_model(),
                "by_model_detail": ct.today_by_model_detail(),
                "call_count": int(ct.today_call_count()),
                "tokens": ct.today_tokens(),
            }
        )

    # ── GET /api/spend/session ──

    async def api_spend_session(request: web.Request) -> web.Response:
        require_api_access(request)
        ct = get_cost_tracker()
        return web.json_response(
            {
                "total_usd": float(ct.session_usd()),
                "by_model_detail": ct.session_by_model_detail(),
                "call_count": int(ct.session_call_count()),
                "tokens": ct.session_tokens(),
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
        return web.json_response({"pricing": ct.pricing_table()})

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
        w.writerow(["date", "usd"])
        for r in rows:
            w.writerow([r["date"], f"{float(r['usd']):.10f}"])

        return web.Response(
            body=buf.getvalue(),
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="thomas_spend_{days}d.csv"',
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
        # Read current settings from preferences
        from thomas.core.persistence import get_preferences_store

        prefs = get_preferences_store().snapshot()
        adv = prefs.get("advanced", {}) if isinstance(prefs, dict) else {}
        rt = adv.get("runtime", {}) if isinstance(adv, dict) else {}
        economy = rt.get("default_token_economy", "optimal") if isinstance(rt, dict) else "optimal"
        autonomy = rt.get("autonomy_level", 3) if isinstance(rt, dict) else 3

        profile = resolve_runtime_profile(
            autonomy_level=autonomy,
            economy_level=economy,
        )
        return web.json_response(profile.to_dict())

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
