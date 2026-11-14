"""One file decides which plugins load, your choices sit on top of it, and nothing here can stop Thomas starting."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import hold_the_first_save
from thomas.core import plugin_manifest
from thomas.server import runtime_plugins
from thomas.server.live_routes import WebService
from thomas.server.runtime_plugins import PROFILE_PATH, RuntimePlugins, UnknownPlugin, read_profile

ROOT = Path(__file__).resolve().parents[1]
ROUTES = "tests.runtime_plugin_fixture:routes"
QUIET = "tests.runtime_plugin_fixture:quiet"
EXPLODES = "tests.runtime_plugin_fixture:explodes"


async def _until(check) -> None:
    while not check():
        await asyncio.sleep(0.01)


def _runtime(tmp_path: Path, rows: list[tuple[str, str, bool]], *, strict: bool = False) -> RuntimePlugins:
    text = 'name = "test"\n'
    for row_id, entry, enabled in rows:
        text += f'[[row]]\nid = "{row_id}"\nentry = "{entry}"\nenabled = {str(enabled).lower()}\n'
    profile = tmp_path / "profile.toml"
    profile.write_text(text, encoding="utf-8")
    service = WebService(web.Application(), None, require_api_access=lambda request: None, read_json=None)
    return RuntimePlugins(
        service, profile_path=profile, choices_path=tmp_path / "plugins" / "choices.json", strict=strict
    )


def _state(runtime: RuntimePlugins, row_id: str) -> str:
    return next(row["state"] for row in runtime.report()["rows"] if row["id"] == row_id)


def test_a_disabled_row_is_never_imported(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, [("off", "tests.a_module_that_does_not_exist:plugin", False)])

    runtime.load()

    assert runtime.report()["rows"] == [
        {
            "id": "off",
            "title": "",
            "about": "",
            "off_means": "",
            "stop_now": "",
            "enabled": False,
            "required": False,
            "state": "off",
            "error": "",
            "waiting_for": 0,
            "stopped_partway": False,
        }
    ]


def test_a_broken_entry_fails_alone_and_the_next_row_still_loads(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path,
        [("broken", "tests.a_module_that_does_not_exist:plugin", True), ("good", ROUTES, True)],
    )

    runtime.load()

    assert _state(runtime, "broken") == "failed"
    assert "ModuleNotFoundError" in runtime.report()["rows"][0]["error"]
    assert _state(runtime, "good") == "active"


def test_strict_hears_about_a_broken_entry(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, [("broken", "tests.a_module_that_does_not_exist:plugin", True)], strict=True)

    with pytest.raises(ModuleNotFoundError):
        runtime.load()


def test_a_plugin_that_raises_fails_alone_and_says_why(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, [("bad", EXPLODES, True), ("good", ROUTES, True)])

    runtime.load()

    assert _state(runtime, "bad") == "failed"
    assert "boom" in runtime.report()["rows"][0]["error"]
    assert _state(runtime, "good") == "active"


def test_a_missing_profile_starts_with_no_plugins_and_says_so(tmp_path: Path) -> None:
    service = WebService(web.Application(), None, require_api_access=None, read_json=None)
    runtime = RuntimePlugins(service, profile_path=tmp_path / "nope.toml", choices_path=tmp_path / "c.json")

    runtime.load()

    assert runtime.report()["rows"] == []
    assert "could not be read" in runtime.report()["notes"][0]


def test_your_saved_choice_wins_over_the_default(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, [("a", ROUTES, True)])
    choices = tmp_path / "plugins" / "choices.json"
    choices.parent.mkdir()
    choices.write_text('{"a": {"enabled": false}}', encoding="utf-8")

    runtime.load()

    assert _state(runtime, "a") == "off"


def test_a_choice_for_a_plugin_that_no_longer_exists_is_ignored(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, [("a", ROUTES, True)])
    choices = tmp_path / "plugins" / "choices.json"
    choices.parent.mkdir()
    choices.write_text('{"gone": {"enabled": false}}', encoding="utf-8")

    runtime.load()

    assert _state(runtime, "a") == "active"


def test_an_unreadable_choices_file_is_reported_and_kept_when_the_next_save_comes(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path, [("a", ROUTES, True)])
        choices = tmp_path / "plugins" / "choices.json"
        choices.parent.mkdir()
        choices.write_text("{not json", encoding="utf-8")

        runtime.load()

        assert _state(runtime, "a") == "active"
        assert "could not be read" in runtime.report()["notes"][0]

        await runtime.turn_off("a")

        kept = list(choices.parent.glob("choices.unreadable-*.json"))
        assert [path.read_text(encoding="utf-8") for path in kept] == ["{not json"]
        assert json.loads(choices.read_text(encoding="utf-8")) == {"a": {"enabled": False}}

    asyncio.run(scenario())


def _damaged(tmp_path: Path) -> RuntimePlugins:
    runtime = _runtime(tmp_path, [("a", QUIET, False)])
    choices = tmp_path / "plugins" / "choices.json"
    choices.parent.mkdir()
    choices.write_text("{not json", encoding="utf-8")
    runtime.load()
    return runtime


def test_a_fresh_copy_ends_the_note_that_promised_one(tmp_path: Path) -> None:
    """The page says "Changing any switch saves a fresh copy." Once one is saved, that sentence is out of date."""

    async def scenario() -> None:
        runtime = _damaged(tmp_path)
        assert runtime.report()["note_codes"] == ["choices_unreadable"]

        await runtime.turn_on("a")

        assert runtime.report()["note_codes"] == []
        assert runtime.report()["notes"] == []

    asyncio.run(scenario())


def test_a_save_that_fails_keeps_the_note_until_one_lands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = _damaged(tmp_path)
        write = runtime_plugins.write_json_atomic

        def full(_path: Path, _payload: object) -> None:
            raise OSError("no room left")

        monkeypatch.setattr(runtime_plugins, "write_json_atomic", full)
        with pytest.raises(OSError, match="no room left"):
            await runtime.turn_on("a")
        assert runtime.report()["note_codes"] == ["choices_unreadable"]

        monkeypatch.setattr(runtime_plugins, "write_json_atomic", write)
        await runtime.turn_off("a")

        assert runtime.report()["note_codes"] == []

    asyncio.run(scenario())


def test_a_press_cancelled_while_it_saves_still_ends_the_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The copy lands whether or not anyone is left to hear it did."""

    async def scenario() -> None:
        saving, release = hold_the_first_save(monkeypatch)
        runtime = _damaged(tmp_path)
        press = asyncio.create_task(runtime.turn_off("a"))
        await _until(saving.is_set)

        press.cancel()
        await asyncio.wait({press})
        release.set()
        await asyncio.get_running_loop().run_in_executor(runtime._saver, lambda: None)  # behind the save
        await asyncio.sleep(0)

        assert runtime.report()["note_codes"] == []

    asyncio.run(scenario())


def test_a_save_ends_only_the_note_it_answers(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _damaged(tmp_path)
        runtime._note("another_problem", "Something else went wrong")

        await runtime.turn_on("a")

        assert runtime.report()["note_codes"] == ["another_problem"]
        assert runtime.report()["notes"] == ["Something else went wrong"]

    asyncio.run(scenario())


def test_off_and_on_move_the_routes_and_remember_the_choice(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert (await client.get("/fixture/hello/you")).status == 200

            await runtime.turn_off("a")
            assert (await client.get("/fixture/hello/you")).status == 404
            assert _state(runtime, "a") == "off"

            await runtime.turn_on("a")
            assert (await client.get("/fixture/hello/you")).status == 200
            assert _state(runtime, "a") == "active"

        choices = tmp_path / "plugins" / "choices.json"
        assert json.loads(choices.read_text(encoding="utf-8")) == {"a": {"enabled": True}}

    asyncio.run(scenario())


def test_off_waits_for_a_running_request_and_a_forced_press_ends_the_wait(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = _runtime(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await _until(lambda: runtime.report()["rows"][0]["waiting_for"] == 1)

            turning_off = asyncio.create_task(runtime.turn_off("a"))
            await _until(lambda: _state(runtime, "a") == "unloading")

            await runtime.turn_off("a", force=True)
            await turning_off

            assert _state(runtime, "a") == "off"
            with pytest.raises(aiohttp.ClientError):  # force ended the work, so the connection ended with it
                await running

    asyncio.run(scenario())


def test_shutting_down_during_a_plain_off_ends_it_and_still_takes_the_other_rows_off(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = _runtime(tmp_path, [("other", QUIET, True), ("one", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await _until(lambda: runtime.report()["rows"][1]["waiting_for"] == 1)
            turning_off = asyncio.create_task(runtime.turn_off("one"))
            await _until(lambda: runtime._rows["one"].fork.stopping)

            await runtime.stop_all()
            await turning_off

            assert _state(runtime, "one") == "off"
            assert _state(runtime, "other") == "off"
            with pytest.raises(aiohttp.ClientError):  # shutdown forced it, so the connection ended with the work
                await running

    asyncio.run(scenario())


def test_turning_on_a_failed_plugin_tries_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path, [("bad", EXPLODES, True)])
        runtime.load()
        assert _state(runtime, "bad") == "failed"

        report = await runtime.turn_on("bad")

        assert report["state"] == "failed"
        assert "boom" in report["error"]

    asyncio.run(scenario())


def test_an_unknown_plugin_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path, [("a", ROUTES, True)])
        runtime.load()

        with pytest.raises(UnknownPlugin):
            await runtime.turn_off("nope")

    asyncio.run(scenario())


def test_the_shipped_rows_provide_no_named_calls() -> None:
    """A row that can be turned off must not provide one: `late.require` stops the server if a provider is missing.

    A required row has no off switch, so it is not held to this: the calls stay provided at import, not by the row.
    """
    manifests = {manifest.name: manifest for manifest in plugin_manifest.load(ROOT)}
    for entry in read_profile(PROFILE_PATH).entries:
        if entry.config.get("required"):
            continue
        module = str(entry.plugin).partition(":")[0]
        source = (ROOT / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        assert "late.provide(" not in source, entry.id
        if entry.id in manifests:
            assert not manifests[entry.id].provides, entry.id
