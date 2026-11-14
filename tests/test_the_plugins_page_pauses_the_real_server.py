"""The Plugins page and the Pause routes, met for the first time: the button on the page pauses a real server and resumes it.

``thomas.server.web`` serves ``settings.plugins-sets.js``, which draws the Pause control; ``thomas.server.rows.pause`` serves
the three routes it talks to and ``thomas.core.pause`` keeps the saved flag. Their own tests stand the other side in, so
neither had met the other. This starts a real scratch server with every plugin on, on a home, a data folder and a project
catalog of its own, presses the button in a real browser and reads the saved flag and the route's answer each time.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import _SERVE, serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

PAGE = "/settings?section=plugins"
PAUSE = "/api/thomas/pause"
WINDOW = {"width": 1280, "height": 900}

# The project catalog is the checkout the code runs from, so the server would list your real projects.
OWN_CATALOG = """\nimport sys
from pathlib import Path

from thomas.server import thomas_project

_catalog = Path(sys.argv[1]).parent / "catalog"
_catalog.mkdir(exist_ok=True)
thomas_project._catalog_root = lambda: _catalog
"""


def _asked(base: str) -> dict[str, Any]:
    with urllib.request.urlopen(base + PAUSE, timeout=30) as answer:  # noqa: S310 - the scratch server on this machine
        return json.loads(answer.read().decode("utf-8"))


def _saved(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "data" / "paused.json").read_text(encoding="utf-8"))


def test_the_button_pauses_a_real_server_and_resume_starts_it_again(tmp_path_factory: pytest.TempPathFactory) -> None:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("pause-page")
    with serving(folder, script=OWN_CATALOG + _SERVE) as base, sync_playwright() as playwright:
        assert _asked(base)["paused"] is False
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=WINDOW)
        page.goto(base + PAGE)
        bar = page.locator("#plugins .plugins-pause")
        bar.wait_for(state="visible", timeout=60000)
        assert "Thomas is working" in bar.inner_text()

        bar.get_by_role("button", name="Pause").click()
        page.wait_for_function(
            "() => document.querySelector('#plugins .plugins-pause-text')?.textContent.includes('Thomas is paused')",
            timeout=30000,
        )
        paused = _asked(base)
        assert paused["paused"] is True and paused["since"]
        assert _saved(folder)["paused"] is True

        # A page that opens while Thomas is paused says so at once.
        again = browser.new_page(viewport=WINDOW)
        again.goto(base + PAGE)
        again.locator("#plugins .plugins-pause").wait_for(state="visible", timeout=60000)
        assert "Thomas is paused" in again.locator("#plugins .plugins-pause").inner_text()

        bar.get_by_role("button", name="Resume").click()
        page.wait_for_function(
            "() => document.querySelector('#plugins .plugins-pause-text')?.textContent.includes('Thomas is working')",
            timeout=30000,
        )
        assert _asked(base)["paused"] is False
        # Resume takes the saved flag away, and a missing flag means not paused.
        assert not (folder / "data" / "paused.json").exists() or _saved(folder)["paused"] is False
        browser.close()
