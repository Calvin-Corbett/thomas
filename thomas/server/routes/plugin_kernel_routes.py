"""Live plugin control: see what is plugged in, and change it without a restart.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). The supervisor in
``thomas/server/plugin_supervisor.py`` can unplug, replug and reload a plugin
while Thomas runs; this is where that becomes something you can actually do.

    GET  /api/plugins/kernel          what is mounted, what is off, what changed,
                                      and which provider answers for each system
    POST /api/plugins/kernel/unplug   {"name": "..."}
    POST /api/plugins/kernel/replug   {"name": "..."}
    POST /api/plugins/kernel/reload   {"name": "...", "force": false}
    POST /api/plugins/kernel/sync     {}

**Every one of these is loopback-only, on top of API access.** Reload imports
Python from the plugins directory into this process; an attacker who could reach
it from another machine would have arbitrary code execution rather than a plugin
toggle. ``require_loopback`` is applied to the mutating routes *and* to the
status route, because the status route names install paths on disk.

The status route answers honestly when plugins are not supervised — some hosts
mount them one-shot, and some never mount them at all. It says which, rather
than returning an empty list that reads like "no plugins installed".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.server.plugin_startup import APP_PLUGIN_SUPERVISOR, APP_PLUGIN_SYSTEMS

RequireAccessFn = Callable[[web.Request], None]
RequireLoopbackFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

log = logging.getLogger(__name__)

#: Where the app keeps the handle returned at startup. Phase 3.3 put a one-shot
#: mount here; 3.5 puts a supervisor here. Both answer ``dispose()``. The key
#: itself comes from ``plugin_startup``, which is what puts the handle there, so
#: this route and that mount cannot drift onto two different strings.
APP_PLUGINS_HANDLE = APP_PLUGIN_SUPERVISOR

#: Reload runs third-party code. These are the ways that fails without being a
#: bug in Thomas; anything else propagates to the error middleware.
_PLUGIN_ERRORS = (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError)


def _supervisor(request: web.Request) -> Any:
    """The live supervisor, or None if this process did not start one."""
    from thomas.server.plugin_supervisor import PluginSupervisor

    handle = request.app.get(APP_PLUGINS_HANDLE)
    return handle if isinstance(handle, PluginSupervisor) else None


def _require_supervisor(request: web.Request) -> Any:
    supervisor = _supervisor(request)
    if supervisor is None:
        raise web.HTTPConflict(
            text="plugins are not supervised in this process; nothing can be swapped live here",
        )
    return supervisor


def _system_rows(request: web.Request) -> list[dict[str, Any]]:
    """One row per plugin system, from the handle startup mounted them under.

    Empty when this process never mounted them, which is a different fact from
    "they are mounted and provide nothing" — hence a list that is empty rather
    than three rows saying ``mounted: false``.
    """
    handle = request.app.get(APP_PLUGIN_SYSTEMS)
    status = getattr(handle, "status", None)
    if not callable(status):
        return []
    rows = status()
    return list(rows) if isinstance(rows, list) else []


def _plugin_name(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="payload must be a JSON object")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise web.HTTPBadRequest(text="name is required")
    return name


def register_plugin_kernel_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    require_loopback: RequireLoopbackFn,
    read_json: ReadJsonFn,
) -> None:
    """Attach the live plugin routes."""

    async def api_status(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)

        from thomas.agent.kernel_wiring import get_kernel
        from thomas.core.kernel import seam_report
        from thomas.server.plugin_kernel_mount import plugin_systems_report

        supervisor = _supervisor(request)
        handle = request.app.get(APP_PLUGINS_HANDLE)
        # The supervisor's kernel, when there is one: reporting the seams of a
        # different kernel than the one holding the plugins is how a status page
        # ends up describing something nobody is running.
        kernel = supervisor.kernel if supervisor is not None else get_kernel()
        return web.json_response(
            {
                "ok": True,
                "hot_swap": supervisor is not None,
                "handle": type(handle).__name__ if handle is not None else "none",
                "kernel": seam_report(kernel),
                "systems": plugin_systems_report(kernel=kernel),
                # The other three systems as the kernel holds them: which service,
                # mounted or not, and the provider answering for it right now.
                "system_services": _system_rows(request),
                "runtime": supervisor.status() if supervisor is not None else {"supervised": False},
            }
        )

    async def api_unplug(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        supervisor = _require_supervisor(request)
        name = _plugin_name(await read_json(request))
        changed = supervisor.unplug(name)
        return web.json_response(
            {
                "ok": changed,
                "name": name,
                "state": "unplugged" if changed else "not mounted",
                "mounted": supervisor.mounted_names(),
            }
        )

    async def api_replug(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        supervisor = _require_supervisor(request)
        name = _plugin_name(await read_json(request))
        try:
            changed = supervisor.replug(name)
        except _PLUGIN_ERRORS as exc:
            log.warning("replug of %r failed: %s", name, exc)
            raise web.HTTPBadRequest(text=f"replug failed: {exc}") from exc
        return web.json_response(
            {
                "ok": changed,
                "name": name,
                "state": "mounted" if changed else "unchanged",
                "mounted": supervisor.mounted_names(),
            }
        )

    async def api_reload(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        supervisor = _require_supervisor(request)
        payload = await read_json(request)
        name = _plugin_name(payload)
        force = bool(payload.get("force")) if isinstance(payload, dict) else False
        try:
            outcome = supervisor.reload(name, force=force)
        except _PLUGIN_ERRORS as exc:
            log.warning("reload of %r failed: %s", name, exc)
            raise web.HTTPBadRequest(text=f"reload failed: {exc}") from exc
        # "failed" is a 200 with ok=False on purpose: the request was handled and
        # the answer — your edit did not load, the previous version is still
        # running — is the useful part. A 500 would lose it.
        return web.json_response(
            {
                "ok": outcome in {"reloaded", "unchanged", "replugged"},
                "name": name,
                "outcome": outcome,
                "mounted": supervisor.mounted_names(),
            }
        )

    async def api_sync(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        supervisor = _require_supervisor(request)
        try:
            report = supervisor.sync()
        except _PLUGIN_ERRORS as exc:
            log.warning("plugin sync failed: %s", exc)
            raise web.HTTPBadRequest(text=f"sync failed: {exc}") from exc
        return web.json_response({"ok": not report["failed"], "changes": report, "mounted": supervisor.mounted_names()})

    app.router.add_get("/api/plugins/kernel", api_status)
    app.router.add_post("/api/plugins/kernel/unplug", api_unplug)
    app.router.add_post("/api/plugins/kernel/replug", api_replug)
    app.router.add_post("/api/plugins/kernel/reload", api_reload)
    app.router.add_post("/api/plugins/kernel/sync", api_sync)
    log.info("Live plugin kernel routes registered")


__all__ = ["APP_PLUGINS_HANDLE", "register_plugin_kernel_routes"]
