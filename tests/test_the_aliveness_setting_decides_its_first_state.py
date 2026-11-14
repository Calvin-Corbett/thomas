"""The aliveness setting is where a Thomas with no saved choice begins, and a saved choice wins over it.

Before the sweep became a plugin, ``THOMAS_ALIVENESS_ENABLED`` was the only way to run it. These start a real server in a
process of its own, on a home and a data folder of its own, and read the plugin, the thread, the file your choices are
saved in and the engine list the tools panel shows, which ``thomas.server.rows.server_diagnostics`` serves.
``thomas.server.aliveness_default`` is what reads the setting, ``thomas.server.rows.aliveness`` is the plugin, ``thomas.core.aliveness`` is the loop it starts, and
``thomas.core.engine_manager`` is the engine list.

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
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core, runtime_plugins

memory, seen_at = sys.argv[1:]


def alive():
    return "thomas-aliveness" in [thread.name for thread in threading.enumerate()]


async def settled(app):
    while any(row["state"] == "loading" for row in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"]):
        await asyncio.sleep(0.05)
    return next(r for r in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"] if r["id"] == "aliveness")


async def listed(client):
    body = await (await client.get("/api/engines")).json()
    return body["engines"]["engines"].get("aliveness")


def saved():
    path = Path(sys.argv[1]).parent / "data" / "plugins" / "choices.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


async def run_the_server():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    async with TestClient(TestServer(app)) as client:
        seen = {"state": (await settled(app))["state"], "thread": alive(), "listed": await listed(client)}
        seen["saved_at_start"] = saved()
        await client.post("/api/plugins/thomas/aliveness/off")
        seen["state_after_off"] = (await settled(app))["state"]
        seen["thread_after_off"] = alive()
        seen["listed_after_off"] = await listed(client)
        await client.post("/api/plugins/thomas/aliveness/on")
        seen["thread_after_on"] = alive()
        seen["listed_after_on"] = await listed(client)
        return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""


def _start(tmp_path: Path, *, setting: str | None, saved: dict[str, Any] | None) -> tuple[dict[str, Any], Path]:
    home = tmp_path / "home"
    data = tmp_path / "data"
    data.mkdir()
    choices = data / "plugins" / "choices.json"
    if saved is not None:
        choices.parent.mkdir()
        choices.write_text(json.dumps(saved), encoding="utf-8")
    env = {
        **os.environ,
        "THOMAS_DATA_DIR": str(data),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
        "THOMAS_PLUGIN_STORAGE": str(tmp_path / "plugin-store"),
        "THOMAS_SEARCH_DB": str(tmp_path / "search.db"),
        "THOMAS_ALIVENESS_LOG": str(tmp_path / "aliveness-log.jsonl"),
        "THOMAS_ALIVENESS_PERMISSIONS": str(tmp_path / "aliveness-permissions.json"),
    }
    env.pop("THOMAS_ALIVENESS_ENABLED", None)
    if setting is not None:
        env["THOMAS_ALIVENESS_ENABLED"] = setting
    seen_at = tmp_path / "seen.json"
    started = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(tmp_path / "memory"), str(seen_at)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert seen_at.is_file(), started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return json.loads(seen_at.read_text(encoding="utf-8")), choices


@pytest.fixture(scope="module")
def no_setting(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    return _start(tmp_path_factory.mktemp("aliveness-no-setting"), setting=None, saved=None)


@pytest.fixture(scope="module")
def setting_and_no_choice(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    return _start(tmp_path_factory.mktemp("aliveness-setting"), setting="1", saved=None)


@pytest.fixture(scope="module")
def setting_and_choice_off(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    saved = {"aliveness": {"enabled": False}}
    return _start(tmp_path_factory.mktemp("aliveness-setting-off"), setting="1", saved=saved)


def test_with_no_setting_and_no_choice_it_begins_off_and_writes_no_choice(
    no_setting: tuple[dict[str, Any], Path],
) -> None:
    seen, _ = no_setting
    assert (seen["state"], seen["thread"]) == ("off", False)
    assert seen["saved_at_start"] is None
    assert seen["listed"]["running"] is False
    assert seen["listed"]["error"] is None


def test_the_engine_list_follows_the_switch_and_a_press_on_needs_no_setting(
    no_setting: tuple[dict[str, Any], Path],
) -> None:
    seen, _ = no_setting
    assert seen["thread_after_on"] is True
    assert seen["listed_after_on"]["running"] is True


def test_with_the_setting_and_no_choice_it_begins_on_and_remembers_that(
    setting_and_no_choice: tuple[dict[str, Any], Path],
) -> None:
    seen, _ = setting_and_no_choice
    assert (seen["state"], seen["thread"]) == ("active", True)
    assert seen["listed"]["running"] is True
    assert seen["saved_at_start"] == {"aliveness": {"enabled": True}}


def test_pressing_off_wins_over_the_setting_for_this_run_and_the_next(
    setting_and_no_choice: tuple[dict[str, Any], Path],
) -> None:
    seen, _ = setting_and_no_choice
    assert (seen["state_after_off"], seen["thread_after_off"]) == ("off", False)
    assert seen["listed_after_off"]["running"] is False


def test_a_saved_off_wins_over_the_setting_at_start(setting_and_choice_off: tuple[dict[str, Any], Path]) -> None:
    seen, _ = setting_and_choice_off
    assert (seen["state"], seen["thread"]) == ("off", False)
    assert seen["listed"]["running"] is False
    assert seen["saved_at_start"] == {"aliveness": {"enabled": False}}
