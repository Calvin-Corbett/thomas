"""Workspace activity leases for long-running Code processes."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_ENGINE_MANAGER


def acquire_code_activity_lease(app: web.Application, run_id: str) -> str:
    manager = app.get(APP_ENGINE_MANAGER)
    begin = getattr(manager, "begin_interactive_work", None)
    return str(begin(f"code:{run_id}") or "") if callable(begin) else ""


def release_code_activity_lease(app: web.Application, token: str) -> None:
    manager = app.get(APP_ENGINE_MANAGER)
    end = getattr(manager, "end_interactive_work", None)
    if token and callable(end):
        end(token)


async def acquire_code_activity_lease_async(app: web.Application, run_id: str) -> str:
    """Acquire off-loop while guaranteeing cancellation cannot orphan the lease."""
    task = asyncio.create_task(asyncio.to_thread(acquire_code_activity_lease, app, run_id))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        token = await task
        release_code_activity_lease(app, token)
        raise


def attach_code_activity_release(task: asyncio.Task[Any], app: web.Application, token: str) -> None:
    task.add_done_callback(lambda _finished: release_code_activity_lease(app, token))
