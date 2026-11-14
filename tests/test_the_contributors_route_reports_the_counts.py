"""``GET /api/contributors`` reports the counts for the copy of Thomas it is pointed at, and only to a caller let in.

Proves thomas.server.routes.contributors and thomas.server.rows.contributors, which serve the counts that
thomas.core.contributors makes. The repository is a temporary one under tmp_path, so nothing reads the real history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.contributors import register_contributors_routes


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Someone")
    _git(path, "config", "user.email", "someone@example.com")
    for name, message in (
        ("a", "plain"),
        ("b", "by claude\n\nThomas-Agent: claude"),
        ("c", "more claude\n\nThomas-Agent: claude"),
    ):
        (path / name).write_text(message, encoding="utf-8")
        _git(path, "add", name)
        _git(path, "commit", "-q", "-m", message)
    return path


async def _ask(repo: Path, guard: Any) -> tuple[int, dict[str, Any]]:
    app = web.Application()
    register_contributors_routes(app, require_api_access=guard, repo=repo)
    async with TestClient(TestServer(app)) as client:
        answer = await client.get("/api/contributors")
        body = await answer.json() if answer.status == 200 else {}
        return answer.status, body


async def test_the_route_reports_the_counts_of_the_copy_it_is_pointed_at(repo: Path) -> None:
    status, body = await _ask(repo, lambda request: None)
    assert status == 200
    assert body["commits"] == 3
    assert body["total"] == {"thomas": 0, "claude": 2, "codex": 0, "you": 1}
    assert body["error"] == ""


async def test_a_folder_with_no_history_is_answered_with_a_sentence_and_no_counts(tmp_path: Path) -> None:
    status, body = await _ask(tmp_path, lambda request: None)
    assert status == 200
    assert body["error"]
    assert body["total"] == {}


async def test_a_caller_the_guard_refuses_gets_no_counts(repo: Path) -> None:
    def refuse(request: web.Request) -> None:
        raise web.HTTPUnauthorized()

    status, body = await _ask(repo, refuse)
    assert status == 401
    assert body == {}
