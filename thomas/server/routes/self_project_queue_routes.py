"""Loopback-only API for booking Thomas projects without starting Build immediately."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from aiohttp import web

from thomas.server import self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.app_keys import local_port, remember_port
from thomas.server.routes import self_project_routes

PATH = "/api/self/projects/queue"


def register_self_project_queue_routes(
    app: web.Application, *, require_loopback: Callable[[web.Request], None]
) -> None:
    async def queue(request: web.Request) -> web.Response:
        require_loopback(request)
        try:
            body = await request.json()
        except ValueError:  # includes JSONDecodeError and UnicodeDecodeError
            return self_project_routes._refuse(400, "the body is not JSON")
        checked = self_project_routes._checked(body)
        if isinstance(checked, web.Response):
            return checked
        port = local_port(request)
        remember_port(request.app, port)
        if port <= 0:
            return self_project_routes._refuse(409, "the server's own port is not known yet; try again in a moment")
        ask, settings, chat_session_id = checked
        try:
            row = await asyncio.to_thread(
                self_project_queue.enqueue, thomas_project._catalog_root(), ask, settings, chat_session_id, port
            )
        except self_project_queue.QueueUnreadable:
            return self_project_routes._refuse(409, "the queue could not be read")
        except (TimeoutError, PermissionError):
            return self_project_routes._refuse(503, "the queue is busy; try again in a moment")
        return web.json_response(row)

    async def listed(request: web.Request) -> web.Response:
        require_loopback(request)
        try:
            listing = await self_project_queue_tick.project_listing(request.app)
            catalog = thomas_project._catalog_root()
            data = await asyncio.to_thread(self_project_queue.read, catalog)
            running = self_project_routes.running_projects(request.app)
            status = await asyncio.to_thread(self_project_queue_tick.queue_status, request.app, data)

            def checked_status(current: dict) -> dict:
                # Compare only memory under the queue lock; resource checks already ran outside it.
                if (
                    current != data
                    or self_project_queue_tick._cached_listing(request.app) is not listing
                    or self_project_routes.running_projects(request.app) != running
                ):
                    capacity = {"running": None, "blocked_by": "Project capacity changed; try again."}
                else:
                    capacity = status
                return {"ok": True, **current, "capacity": capacity}

            result = await asyncio.to_thread(self_project_queue.change, catalog, checked_status)
            if listing.get("unreadable"):
                result["capacity"]["blocked_by"] = (
                    "Thomas projects could not all be read; try again after the list refreshes"
                )
            return web.json_response(result)
        except self_project_queue.QueueUnreadable:
            return self_project_routes._refuse(409, "the queue could not be read")
        except (TimeoutError, PermissionError):
            return self_project_routes._refuse(503, "the queue is busy; try again in a moment")

    async def planner_settings(request: web.Request) -> web.Response:
        require_loopback(request)
        try:
            data = await asyncio.to_thread(self_project_queue.read, thomas_project._catalog_root())
            return web.json_response({"ok": True, "planner": data["planner"]})
        except self_project_queue.QueueUnreadable:
            return self_project_routes._refuse(409, "the queue could not be read")
        except (TimeoutError, PermissionError):
            return self_project_routes._refuse(503, "the queue is busy; try again in a moment")

    async def set_planner(request: web.Request) -> web.Response:
        require_loopback(request)
        try:
            body = await request.json()
        except ValueError:
            return self_project_routes._refuse(400, "the body is not JSON")
        if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
            return self_project_routes._refuse(400, "enabled must be a boolean")

        def update(data: dict) -> dict:
            data["planner"]["enabled"] = body["enabled"]
            return data["planner"].copy()

        try:
            planner = await asyncio.to_thread(self_project_queue.change, thomas_project._catalog_root(), update)
            return web.json_response({"ok": True, "planner": planner})
        except self_project_queue.QueueUnreadable:
            return self_project_routes._refuse(409, "the queue could not be read")
        except (TimeoutError, PermissionError):
            return self_project_routes._refuse(503, "the queue is busy; try again in a moment")

    app.router.add_post(PATH, queue)
    app.router.add_get(PATH, listed)
    app.router.add_get(f"{PATH}/planner", planner_settings)
    app.router.add_put(f"{PATH}/planner", set_planner)
