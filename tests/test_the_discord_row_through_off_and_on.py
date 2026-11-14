"""The Discord row through off and on, with a real bridge program: what a press ends, keeps and brings back.

The bridge here is a real ``node`` process that does nothing, started by the real start route and found again by the real
probe, so a stop that only looked tidy would leave it alive and fail below. Nothing connects to Discord: the token in
these tests is not one.

``thomas.server.rows.discord`` is the row, and it registers the routes of ``thomas.server.routes.discord_channels_aiohttp``. ``tests/test_turning_discord_off_touches_only_its_routes.py`` holds its routes
and ``tests/test_discord_channels.py`` what they do with it on.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run a real bridge program")

START = "/api/channels/discord/start"
STATUS = "/api/channels/discord"


def _bot_root(folder: Path) -> Path:
    root = folder / "bridge"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "discord.js").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"name": "idle-bridge", "private": True}), encoding="utf-8")
    (root / "node_modules" / "discord.js" / "package.json").write_text(
        json.dumps({"name": "discord.js"}), encoding="utf-8"
    )
    (root / "src" / "index.js").write_text("setInterval(() => {}, 1000);\n", encoding="utf-8")
    (root / ".env").write_text(
        "DISCORD_BOT_TOKEN=not-a-token-1234\nDISCORD_OWNER_USER_IDS=111\nTHOMAS_BASE_URL=http://127.0.0.1:9\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[AppConfig, Path, DiscordBridgeRuntime]]:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_SHARED_SECRET_STORE_DIR", str(tmp_path / "shared"))
    root = _bot_root(tmp_path)
    monkeypatch.setenv("THOMAS_DISCORD_BRIDGE_ROOT", str(root))
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
    )
    ours = DiscordBridgeRuntime(config, bridge_root=root)
    try:
        yield config, root, ours
    finally:
        ours.stop()


async def _until(check: Any, *, seconds: float = 60.0) -> None:
    """Each look at the bridge asks Windows about a process, which takes a second, so it is made in a thread."""
    deadline = time.monotonic() + seconds
    while not await asyncio.to_thread(check):
        assert time.monotonic() < deadline, "gave up waiting"
        await asyncio.sleep(0.1)


async def _row_is(plugins: Any, state: str) -> None:
    await _until(lambda: next(r for r in plugins.report()["rows"] if r["id"] == "discord")["state"] == state)


def _marker(ours: DiscordBridgeRuntime) -> Path:
    return ours.state_path.parent / "start_again_when_turned_on"


def test_off_stops_a_running_bridge_and_on_starts_it_again_with_every_setting_kept(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime],
) -> None:
    config, root, ours = world

    async def scenario() -> None:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            plugins = app[APP_RUNTIME_PLUGINS]
            await _row_is(plugins, "active")
            saved = await client.post("/api/channels/discord/config", json={"bot_token": "a-saved-token-5678"})
            assert saved.status == 200
            await client.post("/api/channels/discord/enabled", json={"enabled": True})
            assert (await client.post(START, json={})).status == 200
            assert await asyncio.to_thread(ours.is_running)
            first_pid = ours.load_state()["pid"]
            env_before = (root / ".env").read_text(encoding="utf-8")

            await plugins.turn_off("discord")

            assert not await asyncio.to_thread(ours.is_running)
            assert _marker(ours).is_file()
            assert ours.load_state()["enabled"] is True  # the setting you made
            assert (root / ".env").read_text(encoding="utf-8") == env_before
            assert (await client.post(START, json={})).status == 404
            assert not await asyncio.to_thread(ours.is_running)

            await plugins.turn_on("discord")
            await _until(ours.is_running)

            assert ours.load_state()["pid"] != first_pid
            assert not _marker(ours).exists()
            status = (await (await client.get(STATUS)).json())["discord"]
            assert status["config"]["bot_token_stored"] is True
            assert status["config"]["bot_token_masked"].endswith("5678")
            assert status["bridge"]["enabled"] is True

    asyncio.run(scenario())


def test_turning_it_on_starts_nothing_that_was_not_running_when_it_went_off(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime],
) -> None:
    config, _root, ours = world

    async def scenario() -> None:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            plugins = app[APP_RUNTIME_PLUGINS]
            await _row_is(plugins, "active")
            before = ours.state_path.read_bytes() if ours.state_path.is_file() else None

            await plugins.turn_off("discord")
            await plugins.turn_on("discord")
            await _row_is(plugins, "active")
            await asyncio.sleep(2)

            assert not await asyncio.to_thread(ours.is_running)
            assert not _marker(ours).exists()
            assert (ours.state_path.read_bytes() if ours.state_path.is_file() else None) == before
            assert (await client.get(STATUS)).status == 200

    asyncio.run(scenario())


def test_closing_thomas_stops_a_running_bridge_and_the_next_start_brings_it_back(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime],
) -> None:
    """A stop of the row is what ends the bridge, so closing Thomas ends it too, with the note a press of off leaves."""
    config, _root, ours = world

    async def scenario() -> None:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            await _row_is(app[APP_RUNTIME_PLUGINS], "active")
            assert (await client.post(START, json={})).status == 200
            assert await asyncio.to_thread(ours.is_running)

        assert not await asyncio.to_thread(ours.is_running)
        assert _marker(ours).is_file()

        again = app_core.create_app(config)
        async with TestClient(TestServer(again)):
            await _until(ours.is_running)
            assert not _marker(ours).exists()

    asyncio.run(scenario())


def test_the_runtime_is_built_off_the_event_loop_when_you_turn_it_on(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _root, _ours = world
    built_on: list[tuple[int, int]] = []
    loop_thread: list[int] = []
    original = DiscordBridgeRuntime.__init__

    def recording(self: DiscordBridgeRuntime, *args: Any, **kwargs: Any) -> None:
        built_on.append((threading.get_ident(), loop_thread[0]))
        original(self, *args, **kwargs)

    async def scenario() -> None:
        loop_thread.append(threading.get_ident())
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)):
            plugins = app[APP_RUNTIME_PLUGINS]
            await _row_is(plugins, "active")
            await plugins.turn_off("discord")
            monkeypatch.setattr(DiscordBridgeRuntime, "__init__", recording)
            await plugins.turn_on("discord")
            await _row_is(plugins, "active")

    asyncio.run(scenario())
    assert len(built_on) == 1
    assert built_on[0][0] != built_on[0][1]


def test_a_press_of_off_waits_for_a_bridge_that_is_still_starting(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turned on with a bridge to start again, then off while that start is under way: nothing is left running."""
    config, _root, ours = world
    alive = threading.Event()
    starting = threading.Event()

    def slow_start(self: DiscordBridgeRuntime) -> dict[str, Any]:
        starting.set()
        time.sleep(1.5)
        alive.set()
        return {}

    monkeypatch.setattr(DiscordBridgeRuntime, "start", slow_start)
    monkeypatch.setattr(DiscordBridgeRuntime, "is_running", lambda self: alive.is_set())
    monkeypatch.setattr(DiscordBridgeRuntime, "stop", lambda self: alive.clear() or {})

    async def scenario() -> None:
        _marker(ours).parent.mkdir(parents=True, exist_ok=True)
        _marker(ours).write_text("it was running\n", encoding="utf-8")
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)):
            plugins = app[APP_RUNTIME_PLUGINS]
            await _until(starting.is_set)
            await plugins.turn_off("discord")
            await asyncio.sleep(2.5)  # longer than the start takes, which a stop that did not wait would lose to
            assert not alive.is_set()

    asyncio.run(scenario())


def test_a_press_of_off_waits_for_a_start_that_is_running_and_stop_now_does_not(
    world: tuple[AppConfig, Path, DiscordBridgeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the row's words say of Stop now: it cuts the wait, and a bridge it was starting can still come up."""
    config, _root, _ours = world
    alive = threading.Event()
    starting = threading.Event()

    def slow_start(self: DiscordBridgeRuntime) -> dict[str, Any]:
        starting.set()
        time.sleep(3)
        alive.set()
        return {}

    monkeypatch.setattr(DiscordBridgeRuntime, "start", slow_start)
    monkeypatch.setattr(DiscordBridgeRuntime, "is_running", lambda self: alive.is_set())
    monkeypatch.setattr(DiscordBridgeRuntime, "stop", lambda self: alive.clear() or {})

    async def scenario() -> None:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            plugins = app[APP_RUNTIME_PLUGINS]
            await _row_is(plugins, "active")
            asked = asyncio.ensure_future(client.post(START, json={}))
            await _until(starting.is_set)

            turning_off = asyncio.ensure_future(plugins.turn_off("discord"))
            await asyncio.sleep(1)
            assert not turning_off.done(), "off did not wait for the start that was running"
            assert next(r for r in plugins.report()["rows"] if r["id"] == "discord")["waiting_for"] >= 1
            await plugins.turn_off("discord", force=True)  # Stop now
            await turning_off
            assert isinstance((await asyncio.gather(asked, return_exceptions=True))[0], Exception)  # it fails
            await _until(alive.is_set)  # the start that was cut off finished anyway

            await plugins.turn_on("discord")
            await _row_is(plugins, "active")
            await plugins.turn_off("discord")
            assert not alive.is_set()

    asyncio.run(scenario())
