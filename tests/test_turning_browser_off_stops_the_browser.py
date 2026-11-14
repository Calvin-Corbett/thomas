"""The browser row, off: the Chromium Playwright started is closed, a run that holds a browser tool is refused, and on starts clean.

``thomas.server.rows.browser`` is the row. ``thomas.tools.browser`` holds the Playwright session it closes and
``thomas.tools.browser_parity`` the console and network rows it forgets. ``thomas.server.app_helpers`` and
``thomas.server.worker_runtime`` are where a run is given what the row lent, and ``thomas.agent.kernel_wiring`` is the loan
itself. No test imports a row, so each of those is named here and a change to any of them runs this file.

Playwright is a fake that records what was closed, because a real Chromium is not what is under test: the row either asks
for it to be closed or it does not. ``tests/test_turning_browser_off_touches_only_its_tools.py`` starts a server of its own
with the row off, and by hand the same was done with a real Chromium: one process before Stop, none after, and none after
the server closed.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient

from tests import browser_row_fixture as fake
from tests import plugin_view_fixture as views
from thomas.agent.kernel_wiring import LentTool
from thomas.server.app_helpers import add_tools_rows_lent_the_server
from thomas.server.app_keys import APP_TOOLS
from thomas.tools import browser, browser_parity
from thomas.tools.registry import ToolRegistry


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Your choice to turn the row off is saved in the data folder, so a test that presses it needs its own."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> fake.World:
    return fake.install(monkeypatch)


def test_on_it_lends_all_eight_tools_to_chat_and_to_a_run_in_its_own_folder(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    if importlib.util.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    run_folder = tmp_path / "run"
    run_folder.mkdir()

    async def scenario(client: TestClient, app: Any) -> None:
        assert fake.state(app) == "active"
        assert {t.name for t in app[APP_TOOLS].list_tools() if t.name.startswith("browser.")} == fake.NAMES
        # A run is built from its own folder, and browser.open reads a file there and nowhere else.
        built = ToolRegistry()
        add_tools_rows_lent_the_server(built, app[APP_TOOLS], run_folder)
        # Other plugins lend tools to a run too (notifications does), so look at the browser's own.
        assert {t.name for t in built.list_tools() if t.name.startswith("browser.")} == fake.NAMES
        assert built.get("browser.open").inner._inner._workspace == run_folder
        assert (
            app[APP_TOOLS].get("browser.open").inner._inner._workspace == views.config_in(tmp_path).tools.sandbox_path
        )
        assert world.starts == []  # nothing is launched until a run opens a page

    fake.on_a_server(tmp_path, scenario)


def test_off_closes_what_a_session_started_and_forgets_what_it_recorded(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        await browser._ensure_session_page("default")
        browser_parity.telemetry_for("default")["console"].append({"text": "from the old page"})
        assert len(world.starts) == 1 and not world.starts[0].stopped

        await fake.press(client, app, "off")

        assert fake.state(app) == "off"
        assert world.starts[0].stopped
        assert all(piece.closed for piece in (*world.browsers, *world.contexts, *world.pages))
        assert (browser._STATE.pw, browser._STATE.browser, browser._STATE.sessions) == (None, None, {})
        assert browser_parity._TELEMETRY == {}

    fake.on_a_server(tmp_path, scenario)


def test_on_again_starts_clean_and_launches_nothing_until_a_page_is_opened(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        await browser._ensure_session_page("default")
        await fake.press(client, app, "off")
        await fake.press(client, app, "on")

        assert fake.state(app) == "active"
        assert len(world.starts) == 1 and browser._STATE.sessions == {}
        assert browser_parity.telemetry_for("default")["console"] == []
        await browser._ensure_session_page("default")
        assert len(world.starts) == 2 and not world.starts[1].stopped
        assert world.starts[0].stopped

    fake.on_a_server(tmp_path, scenario)


def test_a_run_that_holds_a_tool_is_refused_at_once_and_cannot_start_the_browser_again(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        chat_copy = app[APP_TOOLS].get("browser.open")
        run_copy = ToolRegistry()
        add_tools_rows_lent_the_server(run_copy, app[APP_TOOLS], tmp_path)
        await fake.press(client, app, "off")

        for held in (chat_copy, run_copy.get("browser.open"), run_copy.get("browser.click")):
            assert isinstance(held, LentTool)
            # The bound only turns a hang into an answer: a refusal is not waiting for anything.
            refused = await asyncio.wait_for(held.safe_execute({"url": "https://example.com"}), 5)
            assert not refused.ok and "browser is turned off" in refused.error
        # A call that got past the refusal before the stop cannot launch Chromium either.
        with pytest.raises(RuntimeError, match="turned off"):
            await browser._ensure_session_page("default")
        assert world.starts == []
        # Tools built from now on, and the set chat reads, no longer carry them.
        assert not any(t.name.startswith("browser.") for t in app[APP_TOOLS].list_tools())
        later = ToolRegistry()
        add_tools_rows_lent_the_server(later, app[APP_TOOLS], tmp_path)
        assert [t for t in later.list_tools() if t.name.startswith("browser.")] == []

    fake.on_a_server(tmp_path, scenario)


def test_a_tool_held_before_off_is_not_revived_by_turning_it_on_again(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    async def scenario(client: TestClient, app: Any) -> None:
        old = app[APP_TOOLS].get("browser.close")
        await fake.press(client, app, "off")
        await fake.press(client, app, "on")
        assert not (await old.safe_execute({})).ok
        assert (await app[APP_TOOLS].get("browser.close").safe_execute({})).ok

    fake.on_a_server(tmp_path, scenario)


def test_closing_the_server_closes_the_browser_a_run_left_open(
    tmp_path: Path, own_data_dir: Path, world: fake.World
) -> None:
    """Nothing stopped Playwright at shutdown before this row."""
    fake.on_a_server(tmp_path, lambda client, app: browser._ensure_session_page("default"))

    assert len(world.starts) == 1
    assert world.starts[0].stopped and all(b.closed for b in world.browsers)


def test_without_playwright_the_row_still_turns_on_and_lends_nothing(
    tmp_path: Path, own_data_dir: Path, world: fake.World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "playwright" else real(name, *a))

    async def scenario(client: TestClient, app: Any) -> None:
        assert fake.state(app) == "active"
        assert not any(t.name.startswith("browser.") for t in app[APP_TOOLS].list_tools())
        await fake.press(client, app, "off")
        await fake.press(client, app, "on")
        assert fake.state(app) == "active"

    fake.on_a_server(tmp_path, scenario)
