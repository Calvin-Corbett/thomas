"""The read-only routes that let you, another AI, or Thomas look into the caged Thomas.

GET only, loopback only, behind the same access guard as the other status routes. The work is
:mod:`thomas.core.cage_inspector`; this file only asks it and answers. Nothing here accepts a command, a write or a path
that is not inside one self-fix copy.

    /api/inspect/processes         what the cage's account is running
    /api/inspect/runs              every run that wrote lately, its last moves, and anything that looks like a loop
    /api/inspect/run/{run}         one run's last moves in order (?n=40)
    /api/inspect/greens            the self-fix copies that exist
    /api/inspect/green/{id}        what that self-fix has changed so far
    /api/inspect/green/{id}/diff   one changed file's diff (?path=)
    /api/inspect/green/{id}/file   one text file from that copy (?path=)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def register_cage_inspector_routes(
    app: Any, *, require_api_access: Any = None, agent_dir: Callable[[], Path], green_root: Callable[[], Path]
) -> None:
    from aiohttp import web

    from thomas.core import cage_inspector

    def _guard(request: Any) -> None:
        if request.remote not in _LOOPBACK or request.headers.get("X-Forwarded-For"):
            raise web.HTTPForbidden(text="the cage can only be looked into from this computer")
        if require_api_access is not None:
            require_api_access(request)

    def _number(request: Any, key: str, default: float) -> float:
        try:
            return float(request.query.get(key) or default)
        except ValueError:
            return default

    async def _answer(request: Any, call: Callable[[], dict[str, Any]]) -> Any:
        _guard(request)
        result = await asyncio.to_thread(call)
        return web.json_response(result, status=200 if result.get("ok") else 404)

    async def api_processes(request: Any) -> Any:
        sample = _number(request, "sample", 1.0)
        return await _answer(request, lambda: cage_inspector.processes(sample_s=sample))

    async def api_runs(request: Any) -> Any:
        hours, last = _number(request, "hours", 3.0), int(_number(request, "last", 10))
        return await _answer(request, lambda: cage_inspector.runs(agent_dir(), hours, max(1, min(last, 50))))

    async def api_run(request: Any) -> Any:
        n = int(_number(request, "n", 40))
        return await _answer(request, lambda: cage_inspector.run_tail(agent_dir(), request.match_info["run"], n))

    async def api_greens(request: Any) -> Any:
        return await _answer(request, lambda: cage_inspector.greens(green_root()))

    async def api_green(request: Any) -> Any:
        return await _answer(request, lambda: cage_inspector.green_status(green_root(), request.match_info["green"]))

    async def api_green_diff(request: Any) -> Any:
        return await _answer(
            request,
            lambda: cage_inspector.green_diff(green_root(), request.match_info["green"], request.query.get("path", "")),
        )

    async def api_green_file(request: Any) -> Any:
        return await _answer(
            request,
            lambda: cage_inspector.green_file(green_root(), request.match_info["green"], request.query.get("path", "")),
        )

    async def api_server(request: Any) -> Any:
        """The server's own loop: how late it has run, and what had the main thread while it was blocked."""
        from thomas.core import event_loop_blame, event_loop_lag

        _guard(request)
        answer = {"ok": True, "loop": event_loop_lag.lag_snapshot(), "blocked_by": event_loop_blame.snapshot()}
        return web.json_response(answer)

    async def api_profile(request: Any) -> Any:
        """Where the server's own threads were busy over ``seconds`` (5 when not given, 30 at most)."""
        from thomas.core import thread_sampler

        _guard(request)
        seconds = _number(request, "seconds", 5.0)
        return web.json_response(await asyncio.to_thread(thread_sampler.profile, seconds))

    async def api_stacks(request: Any) -> Any:
        """Every thread of the server, whole stack, now."""
        from thomas.core import thread_sampler

        _guard(request)
        return web.json_response(await asyncio.to_thread(thread_sampler.stacks))

    app.router.add_get("/api/inspect/server", api_server)
    app.router.add_get("/api/inspect/profile", api_profile)
    app.router.add_get("/api/inspect/stacks", api_stacks)
    app.router.add_get("/api/inspect/processes", api_processes)
    app.router.add_get("/api/inspect/runs", api_runs)
    app.router.add_get("/api/inspect/run/{run}", api_run)
    app.router.add_get("/api/inspect/greens", api_greens)
    app.router.add_get("/api/inspect/green/{green}", api_green)
    app.router.add_get("/api/inspect/green/{green}/diff", api_green_diff)
    app.router.add_get("/api/inspect/green/{green}/file", api_green_file)
