"""Retain delegated task ownership through provider cleanup."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

_TASKS = web.AppKey("delegation_lifecycle_tasks", dict)
log = logging.getLogger(__name__)


def start_owned_delegation(app, execution_id, coroutine):
    registry = app.setdefault(_TASKS, {})
    task = asyncio.create_task(coroutine)
    registry[execution_id] = task

    def finished(done):
        if registry.get(execution_id) is done:
            registry.pop(execution_id, None)
        if not done.cancelled() and done.exception() is not None:
            error = done.exception()
            log.error(
                "Delegated task %s ended with an error",
                execution_id,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(finished)
    return task


async def wait_for_delegation_stop(app, execution_id):
    task = app.get(_TASKS, {}).get(execution_id)
    if task is not None:
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelled():
                raise


def has_live_delegation(app, execution_id):
    task = app.get(_TASKS, {}).get(execution_id)
    return task is not None and not task.done()
