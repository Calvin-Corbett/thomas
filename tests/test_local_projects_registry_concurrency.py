"""Concurrent project-layout updates retain both writes after a registry reread."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.server.routes import local_projects_aiohttp as routes
from thomas.server.routes import local_projects_registry
from thomas.server.routes.local_projects_helpers_aiohttp import _read_registry, _registry_path, _write_registry


class TestLocalProjectRegistryConcurrency(AioHTTPTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self._projects_root = root / "projects"
        self._projects_root.mkdir()
        self.enterContext(patch.dict("os.environ", {"THOMAS_HOME": str(root), "THOMAS_STATE_DIR": str(root)}))
        super().setUp()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmp.cleanup()

    async def get_application(self):
        app = web.Application()
        routes.register_local_project_routes(
            app,
            require_api_access=lambda request: None,
            require_loopback=lambda request: None,
            read_json=lambda request: request.json(),
        )
        return app

    async def test_overlapping_updates_survive_reread(self):
        ids = []
        for name in ("first", "second"):
            root = self._projects_root / name
            root.mkdir()
            (root / "index.html").write_text(name, encoding="utf-8")
            response = await self.client.post("/api/local/projects/import", json={"path": str(root)})
            self.assertEqual(response.status, 200)
            ids.append((await response.json())["project"]["id"])

        entered = threading.Event()
        release = threading.Event()
        original = _read_registry
        calls = 0

        def slow_refresh(app):
            nonlocal calls
            projects = original(app)
            calls += 1
            if calls == 1:
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("first registry refresh did not resume")
            return projects

        async def update(project_id, x):
            response = await self.client.patch(f"/api/local/projects/{project_id}/layout", json={"x": x, "y": x + 1})
            self.assertEqual(response.status, 200)

        with patch.object(routes, "_refresh_projects", side_effect=slow_refresh):
            first = asyncio.create_task(update(ids[0], 101))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                second = asyncio.create_task(update(ids[1], 202))
                await asyncio.sleep(0.05)
                self.assertFalse(second.done(), "the second mutation must wait for the first registry refresh")
            finally:
                release.set()
            await asyncio.gather(first, second)

        positions = {row["id"]: row["board_position"] for row in _read_registry(self.app)}
        self.assertEqual(positions[ids[0]], {"x": 101, "y": 102})
        self.assertEqual(positions[ids[1]], {"x": 202, "y": 203})

    async def test_registry_read_during_replace_never_observes_an_empty_file(self):
        root = self._projects_root / "existing"
        root.mkdir()
        response = await self.client.post("/api/local/projects/import", json={"path": str(root)})
        self.assertEqual(response.status, 200)
        old_projects = _read_registry(self.app)
        registry_path = _registry_path(self.app)
        real_replace = local_projects_registry.os.replace

        def inspect_before_replace(source, target):
            self.assertEqual(target, registry_path)
            self.assertEqual(_read_registry(self.app), old_projects)
            self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8"))["projects"], old_projects)
            real_replace(source, target)

        with patch.object(local_projects_registry.os, "replace", side_effect=inspect_before_replace) as replace:
            await asyncio.to_thread(_write_registry, self.app, old_projects)
        replace.assert_called_once()
        self.assertEqual(_read_registry(self.app), old_projects)
