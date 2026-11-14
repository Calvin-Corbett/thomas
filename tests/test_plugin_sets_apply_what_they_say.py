"""The ready-made plugin sets: the data file is whole, and applying a set presses the same switches as the page.

The row is ``thomas.server.rows.plugin_sets``, its routes are ``thomas.server.ready_made_sets`` and its data is ``thomas/server/rows/sets.toml``. A server is built here
with its own data folder and home, and a set is applied with a request, so what changes is what the switches change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_proof_fixture import ROWS
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core
from thomas.server.ready_made_sets import read_sets
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ALL = [row.id for row in ROWS]
REQUIRED = {row.id for row in ROWS if row.config["required"]}
SETS = read_sets()


def test_every_plugin_is_in_exactly_one_group() -> None:
    """A plugin added later and left out of the groups fails here, so it cannot be missing from the Advanced list."""
    filed = [row_id for group in SETS["groups"] for row_id in group["rows"]]
    assert sorted(filed) == sorted(ALL)
    assert len(filed) == len(set(filed))


def test_a_group_has_a_title_and_some_words() -> None:
    for group in SETS["groups"]:
        assert group["title"].strip() and group["about"].strip() and group["rows"]


def test_a_set_names_only_plugins_that_exist() -> None:
    for chosen in SETS["sets"]:
        assert [row_id for row_id in chosen["rows"] if row_id not in ALL] == [], chosen["id"]
        assert len(chosen["rows"]) == len(set(chosen["rows"])), chosen["id"]


def test_the_three_sets_are_there_and_every_one_keeps_what_cannot_be_turned_off() -> None:
    assert [chosen["id"] for chosen in SETS["sets"]] == ["everyday", "just_chat_and_build", "everything"]
    for chosen in SETS["sets"]:
        assert set(chosen["rows"]) >= REQUIRED, chosen["id"]
        assert "plugin_sets" in chosen["rows"], chosen["id"]


def test_a_set_that_keeps_build_keeps_what_a_build_run_calls_and_reads() -> None:
    """Build teams call back through praxis and Build's project menu reads workspace, per their own words in default.toml."""
    for chosen in SETS["sets"]:
        if "build" in chosen["rows"]:
            assert {"praxis", "workspace"} <= set(chosen["rows"]), chosen["id"]


def test_everyday_keeps_the_pages_the_sidebar_opens() -> None:
    """The Virtual Office and System Map open from the sidebar, so the set for daily use leaves them on."""
    everyday = next(chosen for chosen in SETS["sets"] if chosen["id"] == "everyday")
    assert {"office_state", "system_map"} <= set(everyday["rows"])


def test_everything_names_every_plugin_and_the_smallest_set_is_smaller_than_everyday() -> None:
    by_id = {chosen["id"]: set(chosen["rows"]) for chosen in SETS["sets"]}
    assert by_id["everything"] == set(ALL)
    assert by_id["just_chat_and_build"] < by_id["everyday"] < by_id["everything"]


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "home" / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "home" / "local"))
    monkeypatch.setenv("THOMAS_PLUGIN_STORAGE", str(tmp_path / "plugin-store"))
    monkeypatch.setenv("THOMAS_SEARCH_DB", str(tmp_path / "search.db"))
    return tmp_path / "data"


def _config(tmp_path: Path) -> AppConfig:
    models = {"local": ModelConfig(name="local", model="dummy")}
    return AppConfig(models=models, default_model="local", memory=MemoryConfig(root=str(tmp_path / "memory")))


def _states(app: Any) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in app[APP_RUNTIME_PLUGINS].report()["rows"]}


def test_applying_the_smallest_set_turns_the_rest_off_and_then_everything_turns_them_back_on(
    tmp_path: Path, own_data_dir: Path
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(_config(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            smallest = next(c for c in SETS["sets"] if c["id"] == "just_chat_and_build")
            answer = await client.post("/api/plugins/sets/just_chat_and_build/apply", json={})
            body = await answer.json()
            assert answer.status == 200, body
            states = _states(app)
            on = {row_id for row_id, row in states.items() if row["state"] == "active"}
            assert on == set(smallest["rows"])
            assert set(body["turned_off"]) == set(ALL) - set(smallest["rows"]) - {"aliveness"}
            assert body["turned_on"] == []
            assert body["failed"] == []
            assert {item["id"] for item in body["left_alone"]} == {"plugin_sets", *REQUIRED}
            assert all(item["why"] for item in body["left_alone"])

            answer = await client.post("/api/plugins/sets/everything/apply", json={})
            body = await answer.json()
            assert answer.status == 200, body
            assert set(body["turned_on"]) == set(ALL) - set(smallest["rows"]) | {"aliveness"}
            assert body["turned_off"] == []
            assert {row["state"] for row in _states(app).values()} == {"active"}

    asyncio.run(scenario())


def test_stop_now_cuts_a_set_off_part_way_and_leaves_the_rest_as_they_were(tmp_path: Path, own_data_dir: Path) -> None:
    """The row's words say a set being applied is cut off part way. One plugin's stop is held, so the apply is mid-way."""

    async def scenario() -> None:
        app = app_core.create_app(_config(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            await views.rows_once_started(runtime)
            held = asyncio.Event()
            reached = asyncio.Event()
            real_turn_off = runtime.turn_off

            async def slow_turn_off(row_id: str, *, force: bool = False) -> dict[str, Any]:
                if row_id == "spend":
                    reached.set()
                    await held.wait()
                return await real_turn_off(row_id, force=force)

            runtime.turn_off = slow_turn_off
            applying = asyncio.create_task(client.post("/api/plugins/sets/just_chat_and_build/apply", json={}))
            await asyncio.wait_for(reached.wait(), timeout=60)
            pressing = asyncio.create_task(client.post("/api/plugins/thomas/plugin_sets/off"))
            await asyncio.wait_for(views.until(lambda: _states(app)["plugin_sets"]["state"] == "unloading"), timeout=30)
            assert not pressing.done()

            assert (await client.post("/api/plugins/thomas/plugin_sets/off?force=1")).status == 200
            assert (await asyncio.wait_for(pressing, timeout=30)).status == 200
            held.set()
            await asyncio.gather(applying, return_exceptions=True)

            states = _states(app)
            assert states["plugin_sets"]["state"] == "off"
            still_on = [row_id for row_id in ALL if states[row_id]["state"] == "active"]
            assert len(still_on) > 7, still_on  # the set keeps seven, so more than that means the apply did not finish

    asyncio.run(scenario())
