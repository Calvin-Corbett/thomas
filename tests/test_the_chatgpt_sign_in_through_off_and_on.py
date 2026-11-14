"""What the ChatGPT sign-in row's words say about its listener, a sign-in that waits, and a model already signed in.

A sign-in opens a listener on port 1455 of this machine for ChatGPT's reply, and nothing but a stop closes it. So each test
below swaps ``TCPSite`` for one that binds a scratch port when asked for 1455: no test here binds the real one.
``thomas.server.rows.openai_codex`` is the row and ``thomas.server.routes.openai_codex_aiohttp`` holds the listener. No test
imports a row, and a check follows one import, so naming both here is how it finds this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.core import codex_auth
from thomas.server import app_core
from thomas.server.app_keys import APP_SECRETS
from thomas.server.openai_codex_oauth import write_openai_codex_token
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

SWITCH = "/api/plugins/thomas/openai_codex"
LOGIN = "/api/openai-codex/login"
START = "/api/openai-codex/login/start"


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def listeners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[list[tuple[int, int]]]]:
    """Each listener the sign-in opens, as (address family, port) for every socket it holds. Never port 1455.

    Nothing opens a browser or reads the Codex app's own sign-in from a real folder either.
    """
    opened: list[list[tuple[int, int]]] = []
    real = web.TCPSite

    class _OnAScratchPort(real):  # type: ignore[valid-type, misc]
        def __init__(self, runner: Any, host: Any = None, port: Any = None, **options: Any) -> None:
            super().__init__(runner, host, 0 if port == 1455 else port, **options)

        async def start(self) -> None:
            await super().start()
            opened.append([(item.family, item.getsockname()[1]) for item in self._server.sockets])

    monkeypatch.setattr(web, "TCPSite", _OnAScratchPort)
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("THOMAS_IMPORT_LOCAL_CODEX_AUTH", "0")
    yield opened


def _open(listener: list[tuple[int, int]]) -> list[bool]:
    """Whether each socket of a listener accepts a connection."""
    found = []
    for family, port in listener:
        with socket.socket(family) as probe:
            probe.settimeout(2)
            try:
                probe.connect(("::1" if family == socket.AF_INET6 else "127.0.0.1", port))
                found.append(True)
            except OSError:
                found.append(False)
    return found


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "openai_codex")


async def _until_started(app: web.Application, state: str = "active") -> None:
    await views.until(lambda: _row(app)["state"] == state)


def _a_token() -> dict[str, Any]:
    def encode(part: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(part, separators=(",", ":")).encode()).decode().rstrip("=")

    claims = {
        "exp": int(time.time() + 3600),
        "https://api.openai.com/profile": {"email": "someone@example.com"},
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct_1", "chatgpt_plan_type": "plus"},
    }
    jwt = f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(claims)}.sig"
    return {"access_token": jwt, "refresh_token": "refresh_1", "id_token": jwt, "expires_in": 3600}


def test_off_closes_the_listener_and_on_lets_the_next_sign_in_open_a_new_one(
    tmp_path: Path, own_data_dir: Path, listeners: list[list[tuple[int, int]]]
) -> None:
    """The row's words say both. A listener left open after off would hold the port against the next sign-in."""
    from thomas.server.routes import openai_codex_aiohttp as routes

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await _until_started(app)
            started = await client.post(START, json={"open_browser": False})
            assert (started.status, (await started.json())["callback_bound"]) == (200, True)
            assert len(listeners) == 1
            assert _open(listeners[0]) == [True] * len(listeners[0])

            assert (await client.post(f"{SWITCH}/off")).status == 200
            assert _row(app)["state"] == "off"
            assert _open(listeners[0]) == [False] * len(listeners[0])
            assert routes._CALLBACK_SERVER._pending == {}, "a sign-in not finished is still remembered"
            assert (await client.get("/api/openai-codex/status")).status == 404

            assert (await client.post(f"{SWITCH}/on")).status == 200
            await _until_started(app)
            assert len(listeners) == 1, "turning it on opened a listener nobody asked for"
            assert (await client.get("/api/openai-codex/status")).status == 200

            again = await client.post(START, json={"open_browser": False})
            assert (again.status, (await again.json())["callback_bound"]) == (200, True)
            assert len(listeners) == 2
            assert _open(listeners[1]) == [True] * len(listeners[1])

            assert (await client.post(f"{SWITCH}/off")).status == 200
            assert _open(listeners[1]) == [False] * len(listeners[1])

    asyncio.run(scenario())


def test_a_sign_in_waiting_for_you_holds_the_switch_and_its_reply_can_still_arrive(
    tmp_path: Path, own_data_dir: Path, listeners: list[list[tuple[int, int]]]
) -> None:
    """The row's words say Thomas waits for a sign-in, and that the listener closes when the wait ends."""
    from thomas.server.routes import openai_codex_aiohttp as routes

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await _until_started(app)
            signing_in = asyncio.create_task(client.post(LOGIN, json={"timeout_s": 300}))
            await views.until(lambda: bool(listeners) and bool(routes._CALLBACK_SERVER._pending))
            state = next(iter(routes._CALLBACK_SERVER._pending))

            turning_off = asyncio.create_task(client.post(f"{SWITCH}/off"))
            await _until_started(app, "unloading")
            await asyncio.sleep(0.3)
            assert not turning_off.done()
            assert _row(app)["waiting_for"] == 1
            assert _open(listeners[0]) == [True] * len(listeners[0])

            reply = f"http://127.0.0.1:{next(port for family, port in listeners[0] if family == socket.AF_INET)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{reply}/auth/callback", params={"state": state, "error": "denied"}) as heard:
                    assert heard.status == 200

            answered = await asyncio.wait_for(signing_in, timeout=30)
            assert (answered.status, (await answered.json())["error"]) == (500, "denied")
            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert _row(app)["state"] == "off"
            assert _open(listeners[0]) == [False] * len(listeners[0])

    asyncio.run(scenario())


def test_stop_now_ends_a_waiting_sign_in_and_closes_the_listener(
    tmp_path: Path, own_data_dir: Path, listeners: list[list[tuple[int, int]]]
) -> None:
    """The row's words say Stop now ends a sign-in that is waiting, which then does not complete."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await _until_started(app)
            signing_in = asyncio.create_task(client.post(LOGIN, json={"timeout_s": 300}))
            await views.until(lambda: bool(listeners))
            turning_off = asyncio.create_task(client.post(f"{SWITCH}/off"))
            await _until_started(app, "unloading")
            await asyncio.sleep(0.3)
            assert not turning_off.done()

            assert (await client.post(f"{SWITCH}/off?force=1")).status == 200

            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert _row(app)["state"] == "off"
            assert _open(listeners[0]) == [False] * len(listeners[0])
            ended = (await asyncio.gather(signing_in, return_exceptions=True))[0]
            assert isinstance(ended, Exception) or ended.status != 200, "the sign-in finished anyway"

    asyncio.run(scenario())


def test_a_model_already_signed_in_goes_on_answering_with_the_row_off(
    tmp_path: Path, own_data_dir: Path, listeners: list[list[tuple[int, int]]]
) -> None:
    """The row's words say so: chat reads the saved sign-in through the core resolver, not through these routes."""

    async def scenario() -> tuple[str, str]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await _until_started(app)
            stored = write_openai_codex_token(app[APP_SECRETS], "openai_codex", _a_token(), persist=False)
            assert (await client.post(f"{SWITCH}/off")).status == 200
            assert (await client.get("/api/openai-codex/status")).status == 404
            return stored["access_token"], await codex_auth.resolve_access_token("openai_codex")

    stored, resolved = asyncio.run(scenario())
    assert resolved == stored


def test_a_row_that_cannot_register_reads_failed_and_not_active_with_no_routes(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("a reason you can read")

    monkeypatch.setitem(
        sys.modules, "thomas.server.routes.openai_codex_aiohttp", SimpleNamespace(register_openai_codex_routes=fails)
    )
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.openai_codex"):
        app = app_core.create_app(views.config_in(tmp_path))
    row = _row(app)

    assert row["state"] == "failed", row
    assert "a reason you can read" in row["error"]
    assert "Native ChatGPT/Codex routes unavailable: a reason you can read" in caplog.text


def test_a_server_with_no_access_guard_gets_no_routes(caplog: pytest.LogCaptureFixture) -> None:
    from thomas.server.rows.openai_codex import plugin

    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.openai_codex"):
        with pytest.raises(RuntimeError, match="no access guard"):
            plugin.apply({"web": SimpleNamespace(require_api_access=None)}, {})

    assert "Native ChatGPT/Codex route registration skipped: missing runtime dependencies" in caplog.text
