"""Loopback-only, run-token authenticated channel for Build subprocesses."""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_PRAXIS_RUN_CHANNELS as APP_PRAXIS_RUN_CHANNELS
from thomas.server.praxis.run_channel import RunChannelRegistry


def register_praxis_run_routes(app: web.Application, *, recover_at_startup: bool = True) -> RunChannelRegistry:
    """Add the channel's one route and, the first time, its registry and the stop that suspends every run.

    ``recover_at_startup`` also adds a startup hook that takes in the runs a restart interrupted. The row passes False and
    does that itself when the server is up, because a hook on its view is not waited for and the restart pass reads the
    report straight after.
    """
    registry = app.get(APP_PRAXIS_RUN_CHANNELS)
    if registry is None:
        registry = RunChannelRegistry()
        app[APP_PRAXIS_RUN_CHANNELS] = registry
        if recover_at_startup:
            from thomas.server.praxis.startup import install_praxis_recovery

            install_praxis_recovery(app, registry)

        async def cleanup(_app: web.Application) -> None:
            for run_id in list(registry._runs):
                await registry.suspend(run_id)

        app.on_cleanup.append(cleanup)

    async def command(request: web.Request) -> web.Response:
        try:
            remote = ipaddress.ip_address(str(request.remote or ""))
        except ValueError:
            return web.json_response({"ok": False}, status=403)
        if not remote.is_loopback:
            return web.json_response({"ok": False}, status=403)
        token = request.headers.get("X-Thomas-Run-Token", "")
        channel = registry.get(request.match_info["run_id"], token)
        if channel is None:
            return web.json_response({"ok": False}, status=404)
        try:
            body: Any = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            action = request.match_info["action"]
            if action == "spawn":
                result = {
                    "agents": await channel.spawn(body.get("units"), why_parallel=str(body.get("why_parallel") or ""))
                }
            elif action == "admit_builder":
                result = {
                    "agent": await channel.admit_external_builder(
                        plan_id=str(body.get("plan_id") or ""),
                        title=str(body.get("title") or ""),
                        brief=str(body.get("brief") or ""),
                        path=str(body.get("path") or ""),
                    )
                }
            elif action == "report_builder":
                result = await channel.report_external_builder(
                    str(body.get("agent_id") or ""),
                    body.get("event") or {},
                )
            elif action == "delete":
                result = await channel.delete_files(body.get("paths"), why=str(body.get("why") or ""))
            elif action == "wait":
                result = await channel.wait(
                    body.get("agent_ids") or [], after=body.get("after"), timeout=float(body.get("timeout", 30))
                )
            elif action == "status":
                result = channel.status(body.get("agent_ids"), after=body.get("after"))
            elif action == "stop_child":
                result = await channel.stop_child(str(body.get("agent_id") or ""))
            elif action == "heartbeat":
                report = channel.status()
                result = {"run_id": channel.run_id, "agents": len(report["agents"]), "metrics": report["metrics"]}
            else:
                return web.json_response({"ok": False, "error": "unknown action"}, status=404)
            return web.json_response({"ok": True, **result})
        except (json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    app.router.add_post("/api/praxis/run/{run_id}/{action}", command)
    return registry
