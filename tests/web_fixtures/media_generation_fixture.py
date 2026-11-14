from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.chat.session_store import SessionStore
from thomas.server.app_keys import (
    APP_SECRETS,
    APP_SESSION_LOCKS,
    APP_SESSION_LOCKS_LOCK,
)
from thomas.server.routes import media_generation_routes
from thomas.server.routes.chat_v2_keys import APP_ANNOUNCE_LOCKS, APP_SESSION_STORE
from thomas.server.secrets import SecretStore


class MediaGenerationFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.app = web.Application()
        self.app[APP_SECRETS] = SecretStore(self.data_root / "secrets")
        self.app[APP_SESSION_STORE] = SessionStore(self.data_root / "sessions")
        self.app[APP_SESSION_LOCKS] = {}
        self.app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
        self.app[APP_ANNOUNCE_LOCKS] = {}

        async def responsive(_request):
            return web.json_response({"responsive": True})

        self.app.router.add_get("/probe", responsive)
        self.tasks: set[asyncio.Task[Any]] = set()
        media_generation_routes.setup_media_generation_routes(
            self.app, data_root=self.data_root, start_task=self.start_task
        )
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    def start_task(self, factory: Callable[[], Coroutine[Any, Any, Any]], *, name: str) -> asyncio.Task[Any]:
        """What a row's ``ctx.task`` does here: keep the task, and end it when the test does."""
        task = asyncio.create_task(factory(), name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def asyncTearDown(self) -> None:
        running = list(self.tasks)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await self.client.close()
        self.temp_dir.cleanup()
