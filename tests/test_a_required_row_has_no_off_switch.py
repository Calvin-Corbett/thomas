"""A required row is a plugin with no off switch: it loads whatever you saved, and every way of turning it off is refused.

The words the page shows for it are in tests/test_the_plugins_page_speaks_plainly.py, and the page in the window is in
tests/test_plugins_panel_ui.py. No shipped row is required yet, so each test here marks a throwaway row of its own.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.plugin_page_fixture import allow, report_of
from tests.plugin_view_fixture import state_of
from thomas.server import runtime_plugins
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, Required, load_runtime_plugins

ROUTES = "tests.runtime_plugin_fixture:routes"
FAILS = "tests.runtime_plugin_fixture:fails_starting"
SENTENCE = "Chat window is part of how Thomas works, so it cannot be turned off."


def saved_choices(tmp_path: Path) -> dict | None:
    choices = tmp_path / "data" / "plugins" / "choices.json"
    return json.loads(choices.read_text(encoding="utf-8")) if choices.exists() else None


def served_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, entry: str = ROUTES, saved: str | None = None
) -> web.Application:
    profile = tmp_path / "profile.toml"
    profile.write_text(
        'name = "test"\n[[row]]\nid = "chat_row"\nentry = "' + entry + '"\nrequired = true\ntitle = "Chat window"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", profile)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    if saved is not None:
        choices = tmp_path / "data" / "plugins" / "choices.json"
        choices.parent.mkdir(parents=True)
        choices.write_text(saved, encoding="utf-8")
    app = web.Application()
    load_runtime_plugins(app, None, require_api_access=allow, read_json=None, require_loopback=allow)
    return app


def test_the_report_says_the_row_is_required_and_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = served_required(tmp_path, monkeypatch)[APP_RUNTIME_PLUGINS]
    runtime.mark_ready()

    row = report_of(runtime, "chat_row")

    assert (row["required"], row["enabled"], row["state"]) == (True, True, "active")


def test_a_saved_off_for_a_required_row_is_ignored_on_a_real_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = served_required(tmp_path, monkeypatch, saved='{"chat_row": {"enabled": false}}')[APP_RUNTIME_PLUGINS]
    runtime.mark_ready()

    row = report_of(runtime, "chat_row")

    assert (row["enabled"], row["state"]) == (True, "active")
    assert runtime.report()["notes"] == []


def test_turning_it_off_is_refused_and_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = served_required(tmp_path, monkeypatch)[APP_RUNTIME_PLUGINS]
        runtime.mark_ready()
        for force in (False, True):
            with pytest.raises(Required):
                await runtime.turn_off("chat_row", force=force)
        assert (state_of(runtime, "chat_row"), report_of(runtime, "chat_row")["enabled"]) == ("active", True)
        assert saved_choices(tmp_path) is None

    asyncio.run(scenario())


def test_the_switch_answers_409_in_plain_words_even_when_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        app = served_required(tmp_path, monkeypatch)
        runtime = app[APP_RUNTIME_PLUGINS]
        runtime.mark_ready()
        async with TestClient(TestServer(app)) as client:
            for query in ("", "?force=1"):
                answer = await client.post(f"/api/plugins/thomas/chat_row/off{query}")
                assert answer.status == 409
                assert await answer.text() == SENTENCE
            assert state_of(runtime, "chat_row") == "active"
            assert saved_choices(tmp_path) is None

    asyncio.run(scenario())


def test_turning_it_on_stays_allowed_and_changes_nothing_when_it_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        runtime = served_required(tmp_path, monkeypatch)[APP_RUNTIME_PLUGINS]
        runtime.mark_ready()

        report = await runtime.turn_on("chat_row")

        assert (report["state"], report["enabled"], report["required"]) == ("active", True, True)
        assert saved_choices(tmp_path) == {"chat_row": {"enabled": True}}

    asyncio.run(scenario())


def test_a_required_row_that_failed_can_try_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests import runtime_plugin_fixture as fixture

    async def scenario() -> None:
        fixture.failures_left = 1
        runtime = served_required(tmp_path, monkeypatch, entry=FAILS)[APP_RUNTIME_PLUGINS]
        runtime.mark_ready()
        assert (state_of(runtime, "chat_row"), report_of(runtime, "chat_row")["required"]) == ("failed", True)
        with pytest.raises(Required):
            await runtime.turn_off("chat_row")

        report = await runtime.turn_on("chat_row")

        assert (report["state"], report["error"]) == ("active", "")
        assert saved_choices(tmp_path) == {"chat_row": {"enabled": True}}

    asyncio.run(scenario())
