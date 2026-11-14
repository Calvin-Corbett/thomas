"""Shared fixtures for the Evolve-agent (Build) route tests.

Split out of test_evolve_agent_routes.py (2026-09-23), which had passed the
monolith guard's hard limit and so could not be changed at all. The helpers
are still importable from test_evolve_agent_routes for every existing caller.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server import dial_elevation
from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes
from thomas.server.routes.evolve_agent_routes import (
    register_evolve_agent_routes,
)


class _GateInput:
    def __init__(self) -> None:
        self.data = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _init_repo(root: Path) -> None:
    """Create a throwaway git repo with deterministic identity/signing."""
    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    # A developer's global config may force GPG signing; disable it so a commit
    # in a bare tmp repo cannot hang or fail for unrelated reasons.
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root: Path, message: str = "commit") -> None:
    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", message])


def _new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    return repo


@contextlib.contextmanager
def _owner_raised(*raises: tuple[str, Any]) -> Iterator[None]:
    """What a verified Windows sign-in grants. Since 5213bb30 a dial above its safe
    level runs one level lower until you approve it, which these tests are not about."""
    dial_elevation.reset_grants()
    for dial, value in raises:
        assert dial_elevation.approve(dial, value, authorize=lambda *_args, **_kwargs: True)
    try:
        yield
    finally:
        dial_elevation.reset_grants()


def _drive(
    repo: Path,
    body: Callable[[TestClient], Awaitable[Any]],
    *,
    configure: Callable[[web.Application], None] | None = None,
) -> Any:
    """Build an app with only the evolve-agent routes and run ``body`` against it.

    Wrapped in :func:`asyncio.run` so each test is an ordinary sync function --
    no pytest-asyncio dependency, and ``tmp_path`` composes cleanly.
    """

    async def _runner() -> Any:
        app = web.Application()
        preview_service = register_deliverable_routes(app, require_api_access=lambda _request: None)
        register_evolve_agent_routes(
            app,
            require_api_access=lambda _request: None,  # auth stubbed out
            root_resolver=lambda: repo,
        )
        if configure is not None:
            configure(app)
        client = TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True))
        await client.start_server()
        preview_service.configure(main_origin=str(client.make_url("/")).rstrip("/"))
        try:
            return await body(client)
        finally:
            await client.close()
            await preview_service.stop()

    prior_data_dir = os.environ.get("THOMAS_DATA_DIR")
    os.environ["THOMAS_DATA_DIR"] = str(repo.parent / "thomas-test-data")
    try:
        return asyncio.run(_runner())
    finally:
        if prior_data_dir is None:
            os.environ.pop("THOMAS_DATA_DIR", None)
        else:
            os.environ["THOMAS_DATA_DIR"] = prior_data_dir
