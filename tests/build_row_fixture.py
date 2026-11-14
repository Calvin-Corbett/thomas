"""What the tests of the Build row share: its 42 routes written out by hand, a running server, and a fake process."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.plugin_view_fixture import rows_once_started
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
AGENT = (
    "POST /api/evolve/agent/send",
    "POST /api/evolve/agent/approve",
    "POST /api/evolve/agent/steer",
    "GET /api/evolve/agent/stream",
    "GET /api/evolve/agent/status",
    "POST /api/evolve/agent/stop",
    "POST /api/evolve/agent/pause",
    "POST /api/evolve/agent/resume",
    "POST /api/evolve/agent/message",
    "GET /api/evolve/agent/messages",
    "GET /api/evolve/agent/performance",
    "POST /api/evolve/agent/compact",
    "POST /api/evolve/agent/context-window",
    "POST /api/evolve/agent/answer",
    "GET /api/evolve/agent/live-diff",
    "GET /api/evolve/agent/self-edit/{cid}/status",
    "POST /api/evolve/agent/self-edit/{action}",
    "GET /api/evolve/agent/deliverables",
    "GET /api/evolve/agent/conversations",
    "POST /api/evolve/agent/conversations/new",
    "GET /api/evolve/agent/conversations/{cid}/tree",
    "GET /api/evolve/agent/conversations/{cid}/file",
    "GET /api/evolve/agent/conversations/{cid}/preview",
    "GET /api/evolve/agent/conversations/{cid}",
    "POST /api/evolve/agent/conversations/{cid}/rename",
    "DELETE /api/evolve/agent/conversations/{cid}",
    "GET /api/evolve/agent/changes",
    "POST /api/evolve/agent/revert",
    "POST /api/evolve/agent/keep",
    "POST /api/evolve/agent/checkpoint",
    "GET /api/evolve/agent/artifact-content/{capability}/{cid}/{tail}",
    "GET /api/evolve/agent/artifact/{cid}/{tail}",
    "GET /api/evolve/agent/playtest/stream",
)
LOOP = (
    "GET /api/evolve/loop/status",
    "GET /api/evolve/loop/plan",
    "GET /api/evolve/orchestration/status",
    "GET /api/evolve/orchestration/plan",
    "POST /api/evolve/loop/start",
    "POST /api/evolve/loop/pause",
    "POST /api/evolve/loop/approve/{approval_id}",
    "POST /api/evolve/loop/reject/{approval_id}",
)
ROUTES = (*AGENT, *LOOP)
STREAMS = ("/api/evolve/agent/stream", "/api/evolve/agent/playtest/stream")

# A concrete request for each route, with ids that do not exist, so a route that starts work is asked about nothing.
ASKS = {
    **{route: route.replace("{cid}", "c1").replace("{capability}", "cap").replace("{tail}", "x") for route in AGENT},
    **{route: route.replace("{approval_id}", "a1") for route in LOOP},
}
ASKS["POST /api/evolve/agent/self-edit/{action}"] = "POST /api/evolve/agent/self-edit/nothing"


def named(routes: Any) -> set[str]:
    return {f"{route.method} {route.resource.canonical}" for route in routes if route.resource is not None}


@asynccontextmanager
async def running(tmp_path: Path, *, before_start: Any = None) -> AsyncIterator[tuple[Any, Any, TestClient]]:
    app = app_core.create_app(views.config_in(tmp_path))
    if before_start is not None:
        before_start(app)
    async with TestClient(TestServer(app)) as client:
        runtime = app[APP_RUNTIME_PLUGINS]
        await rows_once_started(runtime)
        yield app, runtime, client


def build_row(runtime: Any) -> dict[str, Any]:
    return next(row for row in runtime.report()["rows"] if row["id"] == "build")


class FakeProcess:
    """What ``asyncio.create_subprocess_exec`` hands back, as far as the loop routes look at it."""

    def __init__(self, *, ends_when_told: bool = True) -> None:
        self.returncode: int | None = None
        self.terminated = 0
        self.killed = 0
        self._ends_when_told = ends_when_told
        self._over = asyncio.Event()

    def terminate(self) -> None:
        self.terminated += 1
        if self._ends_when_told:
            self._end(-15)

    def kill(self) -> None:
        self.killed += 1
        self._end(-9)

    def _end(self, code: int) -> None:
        self.returncode = code
        self._over.set()

    async def wait(self) -> int | None:
        await self._over.wait()
        return self.returncode
