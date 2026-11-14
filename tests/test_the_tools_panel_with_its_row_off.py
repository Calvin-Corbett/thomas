"""The Tools panel on the older full page, with the server-diagnostics row on and off, in a real browser.

The row is ``thomas.server.rows.server_diagnostics`` and its routes are registered by
``thomas.server.server_diagnostics_routes``. The routes, a server started with the row off and a caller with no token are
in ``tests/test_turning_server_diagnostics_off_touches_only_its_routes.py``. The panel reads the engines and the tools from
``thomas/server/web/js/runtime/015_debug_dock.js``, and the command line's check of a running Thomas reads the engines
through ``thomas.cli.parity_gateway_support``.

Every sentence of the row's words is in ``SENTENCES`` with the tests that show it, and the last test fails when a
sentence is added, changed or dropped without this list.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from tests.click_past_easy_setup import click_past_easy_setup, close_easy_setup
from tests.row_page_fixture import _settings, serving
from tests.row_proof_fixture import ROOT, ROWS, choose
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.cli.parity_gateway_support import probe_gateway

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

WORDS = next(row for row in ROWS if row.id == "server_diagnostics").config["words"]
WINDOW = {"width": 1400, "height": 900}
LISTS = ("/api/engines", "/api/tools")
PROOFS = (
    "test_the_tools_panel_with_its_row_off.py",
    "test_turning_server_diagnostics_off_touches_only_its_routes.py",
)
SENTENCES = {
    "Lets other programs, and the Tools panel on the older full page, read the list of engines Thomas runs and the list "
    "of tools it has.": ("test_other_programs_and_the_panel_read_the_engines_and_the_tools",),
    "It also serves the landing heartbeat, which says whether the work in this copy of Thomas has been saved to git, "
    "and how late the server has been in answering.": (
        "test_the_heartbeat_says_whether_work_is_saved_and_how_late_the_server_is",
    ),
    "No page shows the heartbeat.": ("test_no_page_asks_for_the_heartbeat",),
    "While this is off, Thomas keeps its engines and its tools, and other programs cannot read the lists or the "
    "heartbeat.": (
        "test_with_the_row_off_thomas_keeps_its_engines_and_its_tools",
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "The Tools panel then shows no tools and no engines, though Thomas still has them: its Tools tab reads Total 0 and "
    "No tools in registry, and once you press Refresh its System tab reads Engines 0 and No engine rows returned.": (
        "test_with_the_row_off_a_new_panel_shows_no_tools_and_no_engines",
    ),
    "The panel asks when you open its Tools or System tab or press Refresh, and never on its own, so nothing "
    "repeats.": ("test_the_panel_asks_only_when_you_open_a_tab_and_nothing_repeats",),
    "A panel that is already open keeps its lists until you press Refresh.": (
        "test_a_panel_already_open_keeps_its_lists_until_refresh",
    ),
    "The command line's check of a running Thomas then shows its engines as not ok, and still calls Thomas healthy.": (
        "test_with_the_row_off_the_command_line_shows_the_engines_not_ok_and_thomas_healthy",
    ),
}
_KEPT = """\
import asyncio
import json
import sys

from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core, runtime_plugins
from thomas.server.app_keys import APP_ENGINE_MANAGER, APP_TOOLS


async def main():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=sys.argv[1])))
    async with TestClient(TestServer(app)) as client:
        report = app[runtime_plugins.APP_RUNTIME_PLUGINS]
        while any(row["state"] == "loading" for row in report.report()["rows"]):
            await asyncio.sleep(0.05)
        states = {row["id"]: row["state"] for row in report.report()["rows"]}
        print(
            json.dumps(
                {
                    "state": states["server_diagnostics"],
                    "tools": len(app[APP_TOOLS].list_tools()),
                    "engines": sorted(app[APP_ENGINE_MANAGER].status()["engines"]),
                    "answer": (await client.get("/api/tools")).status,
                }
            )
        )


asyncio.run(main())
"""


def _get(base: str, path: str) -> Any:
    with urllib.request.urlopen(base + path, timeout=60) as answer:  # noqa: S310 - a server of this test
        return json.loads(answer.read())


def _post(base: str, path: str) -> int:
    request = urllib.request.Request(
        base + path, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - the same
        return int(answer.status)


def _open_the_panel(browser: Any, base: str) -> tuple[Any, list[str]]:
    page = browser.new_page(viewport=WINDOW)
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url.replace(base, "").partition("?")[0]))
    page.goto(base + "/classic")
    page.wait_for_selector("#app")
    page.wait_for_timeout(6000)
    close_easy_setup(page)
    asked.clear()
    click_past_easy_setup(page, lambda: page.locator("#debugDockToggleBtn"))
    page.wait_for_timeout(3000)
    return page, asked


_READ = "() => document.getElementById('debugDock').innerText"


def _tab(page: Any, name: str) -> str:
    """Open a tab and read it once what it is waiting for has come, which takes longer on a busy machine."""
    page.locator(f'#debugDock [data-debug-tab="{name}"]').first.click()
    if name == "tools":
        page.wait_for_function(
            "() => !document.getElementById('debugDock').innerText.includes('No tools loaded yet')", timeout=60000
        )
    page.wait_for_timeout(500)
    return str(page.evaluate(_READ))


def _refresh(page: Any, comes: str) -> None:
    """Press Refresh until the answer it is expected to bring is there. A press while the panel is loading is ignored."""
    for _ in range(6):
        page.locator('#debugDock button:has-text("Refresh")').first.click()
        try:
            page.wait_for_function(
                "(pattern) => new RegExp(pattern).test(document.getElementById('debugDock').innerText)",
                arg=comes,
                timeout=10000,
            )
            break
        except PlaywrightTimeout:
            continue
    else:
        raise AssertionError(f"Refresh never brought {comes!r}: {page.evaluate(_READ)[:600]!r}")
    page.wait_for_timeout(500)


def _total(text: str) -> int:
    found = re.search(r"TOOL REGISTRY\s+Total\s+(\d+)", text)
    assert found, text[:300]
    return int(found.group(1))


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    seen: dict[str, Any] = {}
    folder = tmp_path_factory.mktemp("tools-panel")
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        seen["engines"] = _get(base, "/api/engines")
        seen["tools"] = _get(base, "/api/tools")
        seen["heartbeat"] = _get(base, "/api/landing-health")
        page, asked = _open_the_panel(browser, base)
        seen["on_before_a_tab"] = {route: asked.count(route) for route in LISTS}
        seen["on_tools_tab"] = _tab(page, "tools")
        seen["on_asks"] = {route: asked.count(route) for route in LISTS}
        _tab(page, "system")
        _refresh(page, r"Engines\s+[1-9]")
        seen["on_system_tab"] = _tab(page, "system")
        seen["pressed_off"] = _post(base, "/api/plugins/thomas/server_diagnostics/off")
        page.wait_for_timeout(3000)
        seen["open_after_off"] = _tab(page, "tools")
        _refresh(page, r"TOOL REGISTRY\s+Total\s+0(?!\d)")
        seen["open_after_refresh"] = _tab(page, "tools")
        page.close()
        new, asked = _open_the_panel(browser, base)
        new.wait_for_timeout(10000)
        seen["off_before_a_tab"] = {route: asked.count(route) for route in LISTS}
        seen["off_tools_tab"] = _tab(new, "tools")
        new.wait_for_timeout(10000)
        seen["off_asks"] = {route: asked.count(route) for route in LISTS}
        _tab(new, "system")
        _refresh(new, "No engine rows returned")
        seen["off_system_tab"] = _tab(new, "system")
        new.close()
        address = urlparse(base)
        seen["probe"] = probe_gateway(str(address.hostname), int(address.port or 0))
        browser.close()
    return seen


@pytest.fixture(scope="module")
def kept(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("diagnostics-kept")
    env = _settings(folder)
    choose(Path(env["THOMAS_DATA_DIR"]), on=[row.id for row in ROWS if row.id != "server_diagnostics"])
    done = subprocess.run(
        [sys.executable, "-c", _KEPT, str(folder / "memory")],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_other_programs_and_the_panel_read_the_engines_and_the_tools(walked: dict[str, Any]) -> None:
    assert walked["engines"]["status"] == "ok" and walked["engines"]["engines"]["engines"], walked["engines"]
    assert walked["tools"]["count"] > 0 and len(walked["tools"]["tools"]) == walked["tools"]["count"]
    assert _total(walked["on_tools_tab"]) == walked["tools"]["count"]
    assert "No engine rows returned" not in walked["on_system_tab"]
    assert re.search(r"Engines\s+[1-9]", walked["on_system_tab"]), walked["on_system_tab"][:500]


def test_the_heartbeat_says_whether_work_is_saved_and_how_late_the_server_is(walked: dict[str, Any]) -> None:
    heartbeat = walked["heartbeat"]
    assert isinstance(heartbeat["severity"], str)
    assert heartbeat["headline"] and heartbeat["sentences"]
    assert {"max_lag_s", "mean_lag_s", "budget_s", "responsive"} <= set(heartbeat["event_loop"])
    assert {"calls", "seconds_off_loop"} <= set(heartbeat["off_loop"])


def test_no_page_asks_for_the_heartbeat() -> None:
    """The words say no page shows it. A caller added to a page means they must be read again."""
    web = ROOT / "thomas" / "server" / "web"
    pages = [
        path.name
        for path in web.rglob("*")
        if path.suffix in {".js", ".html"} and "landing-health" in path.read_text(encoding="utf-8")
    ]
    assert pages == []


def test_with_the_row_off_thomas_keeps_its_engines_and_its_tools(kept: dict[str, Any]) -> None:
    assert kept["state"] == "off"
    assert kept["tools"] > 0
    assert "persistence" in kept["engines"], kept["engines"]
    assert kept["answer"] == 404


def test_with_the_row_off_a_new_panel_shows_no_tools_and_no_engines(walked: dict[str, Any]) -> None:
    assert walked["pressed_off"] == 200
    assert _total(walked["off_tools_tab"]) == 0
    assert "No tools in registry" in walked["off_tools_tab"]
    assert re.search(r"Engines\s+0\b", walked["off_system_tab"]), walked["off_system_tab"][:500]
    assert "No engine rows returned" in walked["off_system_tab"]


def test_the_panel_asks_only_when_you_open_a_tab_and_nothing_repeats(walked: dict[str, Any]) -> None:
    """Nothing before the first tab, one ask for each list at it, and still one after ten more seconds."""
    none = {"/api/engines": 0, "/api/tools": 0}
    once = {"/api/engines": 1, "/api/tools": 1}
    assert (walked["on_before_a_tab"], walked["on_asks"]) == (none, once)
    assert (walked["off_before_a_tab"], walked["off_asks"]) == (none, once)


def test_a_panel_already_open_keeps_its_lists_until_refresh(walked: dict[str, Any]) -> None:
    assert _total(walked["open_after_off"]) == walked["tools"]["count"]
    assert _total(walked["open_after_refresh"]) == 0


def test_with_the_row_off_the_command_line_shows_the_engines_not_ok_and_thomas_healthy(walked: dict[str, Any]) -> None:
    probe = walked["probe"]
    assert (probe["engines"]["ok"], probe["engines"]["status"]) == (False, 404), probe["engines"]
    assert probe["healthy"] is True, probe


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none lands on the strength of having been true once."""
    written = [*re.split(r"(?<=\.)\s+", WORDS["about"]), *re.split(r"(?<=\.)\s+", WORDS["off_means"])]
    assert written == list(SENTENCES)
    proofs = "".join((ROOT / "tests" / name).read_text(encoding="utf-8") for name in PROOFS)
    named = {name for names in SENTENCES.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()
