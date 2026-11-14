"""The Publish to GitHub routes build a preview off the loop, ask for the guard, and send only after a sign-in.

Proves thomas.server.routes.public_release_routes and thomas.server.rows.public_release. A stand-in backend takes the
place of the release tool, so nothing is built from the checkout and nothing reaches GitHub.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes import public_release_routes as routes


class FakePreview:
    def __init__(self) -> None:
        self.closed = False

    def digest(self) -> str:
        return "digest-1"

    def to_dict(self) -> dict[str, Any]:
        return {"version": "1.2.3", "digest": "digest-1", "files": 5, "removed": {}, "checks": []}

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    def __init__(self, *, signs: bool = True, ok: bool = True) -> None:
        self.signs, self.ok = signs, ok
        self.release = threading.Event()
        self.built: list[FakePreview] = []
        self.calls: list[str] = []
        self.release.set()

    def build(self) -> FakePreview:
        self.release.wait(10)
        self.built.append(FakePreview())
        return self.built[-1]

    def confirm(self, preview: Any) -> object | None:
        self.calls.append("confirm")
        return object() if self.signs else None

    def publish(self, preview: Any, record: Any, open_pr: bool) -> Any:
        self.calls.append(f"publish open_pr={open_pr}")
        return SimpleNamespace(
            ok=self.ok,
            dry_run=False,
            lines=["Sent."],
            branch="release/1.2.3-x",
            branch_url="u",
            pr_url="",
            signed=False,
        )


def _spawn(factory: Any, *, name: str) -> asyncio.Task[Any]:
    return asyncio.get_running_loop().create_task(factory(), name=name)


async def _client(backend: FakeBackend, guard: Any = None, loopback: Any = None):
    jobs = routes.ReleaseJobs(backend, _spawn)
    app = web.Application()

    async def read_json(request: web.Request) -> Any:
        return await request.json()

    routes.register_public_release_routes(
        app,
        jobs=jobs,
        require_api_access=guard or (lambda request: None),
        require_loopback=loopback or (lambda request: None),
        read_json=read_json,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, jobs


async def _ready(client: TestClient) -> dict[str, Any]:
    for _ in range(100):
        body = await (await client.get("/api/public-release/preview")).json()
        if body["state"] != "working":
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("the preview never finished")


def test_the_first_ask_starts_a_build_off_the_loop_and_says_working() -> None:
    async def go() -> None:
        backend = FakeBackend()
        backend.release.clear()
        client, jobs = await _client(backend)
        first = await (await client.get("/api/public-release/preview")).json()
        second = await (await client.get("/api/public-release/preview")).json()
        assert first == {"state": "working", "message": ""} == second
        backend.release.set()
        done = await _ready(client)
        assert done["state"] == "ready" and done["preview"]["version"] == "1.2.3"
        assert len(backend.built) == 1  # asking again while it worked started nothing new
        await jobs.stop()
        await client.close()

    asyncio.run(go())


def test_a_failed_build_says_why_in_words() -> None:
    class Broken(FakeBackend):
        def build(self) -> FakePreview:
            raise RuntimeError("no development copy")

    async def go() -> None:
        client, jobs = await _client(Broken())
        done = await _ready(client)
        assert done == {"state": "failed", "message": "The preview could not be made: no development copy"}
        await client.close()

    asyncio.run(go())


def test_publishing_needs_the_digest_of_the_preview_on_screen() -> None:
    async def go() -> None:
        backend = FakeBackend()
        client, jobs = await _client(backend)
        none_yet = await client.post("/api/public-release/publish", json={"preview_digest": "digest-1"})
        await _ready(client)
        wrong = await client.post("/api/public-release/publish", json={"preview_digest": "other"})
        assert none_yet.status == wrong.status == 409
        assert backend.calls == []
        await jobs.stop()
        await client.close()

    asyncio.run(go())


def test_a_declined_sign_in_publishes_nothing() -> None:
    async def go() -> None:
        backend = FakeBackend(signs=False)
        client, jobs = await _client(backend)
        await _ready(client)
        answer = await client.post("/api/public-release/publish", json={"preview_digest": "digest-1"})
        assert answer.status == 403
        assert (await answer.json())["lines"] == ["You did not sign in with Windows, so nothing was published."]
        assert backend.calls == ["confirm"]
        await jobs.stop()
        await client.close()

    asyncio.run(go())


def test_a_signed_in_release_is_published_once_and_the_preview_is_used_up() -> None:
    async def go() -> None:
        backend = FakeBackend()
        client, jobs = await _client(backend)
        await _ready(client)
        done = await client.post("/api/public-release/publish", json={"preview_digest": "digest-1", "open_pr": True})
        body = await done.json()
        assert done.status == 200 and body["ok"] and body["branch"] == "release/1.2.3-x"
        assert backend.calls == ["confirm", "publish open_pr=True"]
        assert backend.built[0].closed and jobs.state == routes.IDLE
        again = await client.post("/api/public-release/publish", json={"preview_digest": "digest-1"})
        assert again.status == 409
        await client.close()

    asyncio.run(go())


def test_a_refused_release_is_reported_with_its_reason() -> None:
    async def go() -> None:
        client, jobs = await _client(FakeBackend(ok=False))
        await _ready(client)
        answer = await client.post("/api/public-release/publish", json={"preview_digest": "digest-1"})
        assert answer.status == 409 and (await answer.json())["ok"] is False
        await jobs.stop()
        await client.close()

    asyncio.run(go())


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/public-release/preview"), ("POST", "/api/public-release/publish")]
)
def test_both_routes_ask_the_access_guard_and_the_loopback_guard_the_server_hands_them(method: str, path: str) -> None:
    def refuse(request: web.Request) -> None:
        raise web.HTTPUnauthorized()

    def not_here(request: web.Request) -> None:
        raise web.HTTPForbidden()

    async def go() -> None:
        backend = FakeBackend()
        shut, away = await _client(backend, guard=refuse), await _client(backend, loopback=not_here)
        for (client, jobs), status in ((shut, 401), (away, 403)):
            answer = await client.request(method, path, json={})
            assert answer.status == status
            await client.close()
        assert backend.built == [] and backend.calls == []

    asyncio.run(go())


def test_a_stop_throws_the_preview_away_and_a_build_that_ends_after_it_closes_its_own_copy() -> None:
    async def go() -> None:
        backend = FakeBackend()
        client, jobs = await _client(backend)
        await _ready(client)
        await jobs.stop()
        assert backend.built[0].closed and jobs.preview is None

        late = FakeBackend()
        late.release.clear()
        client2, jobs2 = await _client(late)
        await client2.get("/api/public-release/preview")
        await jobs2.stop()
        late.release.set()
        for _ in range(100):
            if late.built:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        assert late.built[0].closed and jobs2.preview is None
        await client.close()
        await client2.close()

    asyncio.run(go())


def test_a_copy_without_the_release_tool_says_so_in_words(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setitem(sys.modules, "scripts.forge.publish.public_release", None)

    with pytest.raises(RuntimeError, match="needs the development copy of Thomas"):
        routes.CheckoutBackend(tmp_path).build()
