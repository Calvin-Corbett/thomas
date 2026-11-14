"""Turning the aliveness plugin off waits for a look that is partway through, and Stop now ends only the wait.

The row's words say so, so this holds each sentence of them on a real server in a process of its own: the stop waits
while a look is partway through, Stop now makes the row read off with that look still running, the look then finishes by
itself and may still write down what it found, and a look that has ended leaves no thread. ``thomas.server.rows.aliveness``
is the plugin and ``thomas.core.aliveness`` is the loop it stops.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.row_proof_fixture import ROOT

_SCRIPT = """\
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from thomas.core.aliveness_world import Observation
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core, runtime_plugins

memory, seen_at, log_at = sys.argv[1:]
release = threading.Event()
inside = threading.Event()


class Blocking:
    name = "blocking"
    calls = 0

    def sample(self):
        Blocking.calls += 1
        if Blocking.calls == 2:  # the first look is the baseline, and the second is the one that stays partway through
            inside.set()
            release.wait(30)
        return [Observation("fake.topic", "branch", f"look {Blocking.calls}", time.time())]


def alive():
    return "thomas-aliveness" in [thread.name for thread in threading.enumerate()]


def row_of(app):
    return next(r for r in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"] if r["id"] == "aliveness")


async def until(condition, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.02)
    return False


def logged():
    path = Path(log_at)
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


async def run_the_server():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    async with TestClient(TestServer(app)) as client:
        while any(r["state"] == "loading" for r in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"]):
            await asyncio.sleep(0.05)
        await client.post("/api/plugins/thomas/aliveness/on")
        from thomas.core import aliveness

        aliveness._loop.world._sensors = [Blocking()]
        seen = {"inside": await asyncio.to_thread(inside.wait, 20)}
        pressed = asyncio.ensure_future(client.post("/api/plugins/thomas/aliveness/off"))
        await until(lambda: row_of(app)["state"] == "unloading")
        await asyncio.sleep(2.6)  # longer than the two seconds a plain stop gives a look before it gives up
        seen["waiting_state"] = row_of(app)["state"]
        seen["waiting_thread"] = alive()
        seen["press_returned_while_waiting"] = pressed.done()
        logged_before = logged()
        forced = await client.post("/api/plugins/thomas/aliveness/off?force=1")
        seen["forced"] = forced.status
        seen["forced_state"] = row_of(app)["state"]
        seen["forced_thread"] = alive()
        release.set()
        seen["ended"] = await until(lambda: not alive())
        seen["wrote_after"] = logged() - logged_before
        seen["unloaded_row"] = row_of(app)["state"]
        await asyncio.wait_for(pressed, 20)
        return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp("aliveness-stop-now")
    home = tmp_path / "home"
    data = tmp_path / "data"
    (data / "plugins").mkdir(parents=True)
    (data / "plugins" / "choices.json").write_text(json.dumps({"aliveness": {"enabled": False}}), encoding="utf-8")
    log_at = tmp_path / "aliveness-log.jsonl"
    env = {
        **os.environ,
        "THOMAS_DATA_DIR": str(data),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
        "THOMAS_PLUGIN_STORAGE": str(tmp_path / "plugin-store"),
        "THOMAS_SEARCH_DB": str(tmp_path / "search.db"),
        "THOMAS_ALIVENESS_LOG": str(log_at),
        "THOMAS_ALIVENESS_PERMISSIONS": str(tmp_path / "aliveness-permissions.json"),
        "THOMAS_ALIVENESS_INTERVAL_S": "0.1",
    }
    env.pop("THOMAS_ALIVENESS_ENABLED", None)
    seen_at = tmp_path / "seen.json"
    started = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(tmp_path / "memory"), str(seen_at), str(log_at)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert seen_at.is_file(), started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return json.loads(seen_at.read_text(encoding="utf-8"))


def test_a_stop_waits_for_the_look_it_is_partway_through(seen: dict[str, Any]) -> None:
    assert seen["inside"] is True, "the test never got a look partway through"
    assert seen["waiting_state"] == "unloading"
    assert seen["waiting_thread"] is True
    assert seen["press_returned_while_waiting"] is False


def test_stop_now_ends_the_wait_and_leaves_that_look_running_by_itself(seen: dict[str, Any]) -> None:
    assert seen["forced"] == 200
    assert seen["forced_state"] == "off"
    assert seen["forced_thread"] is True


def test_that_look_ends_without_starting_another_and_may_still_write_down_what_it_found(seen: dict[str, Any]) -> None:
    assert seen["ended"] is True
    assert seen["wrote_after"] >= 1
    assert seen["unloaded_row"] == "off"
