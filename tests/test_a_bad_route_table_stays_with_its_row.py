"""A row's bad routes are that row's: it fails with the reason, whoever's press found it, and the rest carry on."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_page_fixture import OFF, ON, ROUTES, served
from tests.plugin_view_fixture import Adds, ok, row_here, runtime_with, state_of
from thomas.server import runtime_plugins
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, load_runtime_plugins

HERE = __name__
folder: Path | None = None  # what the row that serves a folder serves


class _ServesAFolder:
    name = "serves-a-folder"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        view = ctx["web"].view(ctx)
        view.router.add_static("/files/", str(folder))
        view.router.add_get("/files-too", ok)


get_claimed = Adds("GET", "/claimed")
get_other = Adds("GET", "/other")
needs_a_thing_and_claims = Adds("GET", "/claimed", "thing")
needs_a_thing_and_claims_every_method = Adds("*", "/claimed", "thing")
needs_a_thing_and_posts = Adds("POST", "/claimed", "thing")
serves_a_folder = _ServesAFolder()


def _error(runtime: Any, row_id: str) -> str:
    return next(row["error"] for row in runtime.report()["rows"] if row["id"] == row_id)


# -- the press was another row's ----------------------------------------------


def test_a_dependant_with_the_bad_table_fails_and_its_provider_stays_up(tmp_path: Path) -> None:
    """The press was on the provider, and the provider did nothing wrong."""

    async def scenario() -> None:
        rows = [
            row_here(HERE, "get_claimed"),
            row_here(HERE, "needs_a_thing_and_claims"),
            ("provider", f"{fixture.HERE}:provides_a_thing", False),
        ]
        runtime = runtime_with(tmp_path, rows)
        runtime.load()
        runtime.mark_ready()
        assert state_of(runtime, "needs_a_thing_and_claims") == "pending"

        report = await runtime.turn_on("provider")

        assert report["state"] == "active"
        assert report["error"] == ""
        assert state_of(runtime, "needs_a_thing_and_claims") == "failed"
        assert "/claimed" in _error(runtime, "needs_a_thing_and_claims")
        assert state_of(runtime, "get_claimed") == "active"

        await runtime.turn_off("get_claimed")
        assert (await runtime.turn_on("needs_a_thing_and_claims"))["state"] == "active"  # and it can be tried again

    asyncio.run(scenario())


def test_a_row_refused_for_a_claim_holds_no_claim(tmp_path: Path) -> None:
    """One press brings two rows up. The first is refused, so the second meets what is left, not the row that was refused."""

    async def scenario() -> None:
        rows = [
            row_here(HERE, "get_claimed"),
            row_here(HERE, "needs_a_thing_and_claims_every_method"),
            row_here(HERE, "needs_a_thing_and_posts"),
            ("provider", f"{fixture.HERE}:provides_a_thing", False),
        ]
        runtime = runtime_with(tmp_path, rows)
        runtime.load()
        runtime.mark_ready()

        await runtime.turn_on("provider")

        assert state_of(runtime, "needs_a_thing_and_claims_every_method") == "failed"
        assert state_of(runtime, "needs_a_thing_and_posts") == "active"

    asyncio.run(scenario())


# -- a row's own table going bad later ----------------------------------------


def _with_a_folder(tmp_path: Path, *more: tuple[str, str, bool]) -> Any:
    global folder
    folder = tmp_path / "files"
    folder.mkdir()
    runtime = runtime_with(tmp_path, [row_here(HERE, "serves_a_folder"), *more])
    runtime.load()
    runtime.mark_ready()
    return runtime


def test_a_folder_that_vanished_fails_its_own_row_and_no_other(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _with_a_folder(tmp_path, row_here(HERE, "get_other"), row_here(HERE, "get_claimed", on=False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            shutil.rmtree(folder)

            report = await runtime.turn_on("get_claimed")

            assert report["state"] == "active"
            assert state_of(runtime, "serves_a_folder") == "failed"
            assert "ValueError" in _error(runtime, "serves_a_folder")
            assert state_of(runtime, "get_other") == "active"
            assert (await client.get("/other")).status == 200
            assert (await client.get("/claimed")).status == 200
            assert (await client.get("/files-too")).status == 404  # a row is one table, so all of it leaves

    asyncio.run(scenario())


def test_off_answers_for_another_row_when_a_folder_has_vanished(tmp_path: Path, monkeypatch: Any) -> None:
    """Through the real route, because what used to come back here was a 500, for a row nobody had pressed."""

    async def scenario() -> None:
        global folder
        folder = tmp_path / "files"
        folder.mkdir()
        rows = [row_here(HERE, "serves_a_folder"), row_here(HERE, "get_other")]
        monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", fixture.profile_at(tmp_path / "profile.toml", rows))
        monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
        app = web.Application()
        allow = lambda _request: None  # noqa: E731 - the real guards have tests of their own
        load_runtime_plugins(app, None, require_api_access=allow, read_json=None, require_loopback=allow)
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            shutil.rmtree(folder)

            answer = await client.post("/api/plugins/thomas/get_other/off")

            assert answer.status == 200
            assert (await answer.json())["state"] == "off"
            assert state_of(runtime, "serves_a_folder") == "failed"

    asyncio.run(scenario())


def test_a_row_whose_folder_vanished_can_be_turned_off_and_tried_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _with_a_folder(tmp_path, row_here(HERE, "get_other"))
        shutil.rmtree(folder)
        await runtime.turn_off("get_other")
        assert state_of(runtime, "serves_a_folder") == "failed"

        assert (await runtime.turn_off("serves_a_folder"))["state"] == "off"
        assert (await runtime.turn_on("serves_a_folder"))["state"] == "failed"  # still gone, and it says so

        folder.mkdir()
        assert (await runtime.turn_on("serves_a_folder"))["state"] == "active"
        assert (await runtime.turn_on("get_other"))["state"] == "active"

    asyncio.run(scenario())


def _falls_over() -> None:
    raise OSError("the list could not be rebuilt")


def test_a_rebuild_that_raises_does_not_cost_a_press_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """It came through publish and turned a press that had worked into a 500, with the row already changed."""

    async def scenario() -> None:
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        rebuilt: list[str] = []
        runtime.web.after_publish(_falls_over)
        runtime.web.after_publish(lambda: rebuilt.append("the next one still ran"))
        async with TestClient(TestServer(app)) as client:
            off = await client.post(OFF)
            assert (off.status, (await off.json())["state"]) == (200, "off")
            assert (await client.get("/fixture/hello/you")).status == 404

            on = await client.post(ON)
            assert (on.status, (await on.json())["state"]) == (200, "active")
            assert (await client.get("/fixture/hello/you")).status == 200

        assert "the list could not be rebuilt" in caplog.text
        assert "the next one still ran" in rebuilt

    asyncio.run(scenario())


def test_strict_hears_about_a_rebuild_that_raises(tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [])
    runtime.web.after_publish(_falls_over)

    with pytest.raises(OSError, match="could not be rebuilt"):
        runtime.web.publish(strict=True)


def test_strict_hears_about_a_table_gone_bad(tmp_path: Path) -> None:
    """What a plugin author wants while finding out why a table went bad, and nothing a running Thomas does."""

    async def scenario() -> None:
        runtime = _with_a_folder(tmp_path, row_here(HERE, "get_other"))
        shutil.rmtree(folder)

        with pytest.raises(ValueError):
            runtime.web.publish(strict=True)

    asyncio.run(scenario())
