"""The Asset Studio page through off and on, read from a real window on a real server, and the row's words against it.

The words of ``thomas.server.rows.asset_studio`` are in ``thomas/server/rows/default.toml``, and they say what you see, so
each sentence is listed below with the tests that show it. Change the words or the page and this fails until the two
agree. No button opens this page, so these tests go to it by its address. A ComfyUI here is a real server in a process of
its own, because a reloaded page says offline about one that is up.

The page's code is ``041_model_setup_settings_02.js`` and ``042_model_setup_settings_03.js``, and the second replaces the
first. It calls ``thomas.server.routes.asset_studio_aiohttp``. Those names are how a check finds this file when one of
them changes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.asset_studio_fixture import comfy_is_up, comfy_script, end_comfy, free_port
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server.runtime_plugins import PROFILE_PATH

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

ROW = "asset_studio"
SIDEBAR = "#tc-workspaces"
PANEL = "[data-studio-comfy-shell-host]"
OFFLINE = "Comfy is offline. Click Boot to start the managed session."
ROUTES_PREFIX = "/api/asset-studio/v1/"
TEN_SECONDS = 10_000
# Asks in ten seconds, from anywhere on the page. Its whole start is 23 asks, on or off, spread over about a minute, and
# where those fall in a window of ten seconds depends on the machine. The Marketplace page's loop asked about 280.
LOOPING = 50
# The sentences below are shown by these two files and this one.
OFF_TEST = "test_turning_asset_studio_off_touches_only_its_routes.py"
JOBS_TEST = "test_asset_studio_jobs_through_off_and_on.py"
OFF_MEANS = {
    "While this is off, nothing you normally use changes, because no button in the sidebar or Settings opens the Asset "
    "Studio page and no page shows these jobs.": (
        "test_no_button_opens_the_page",
        "test_the_only_page_that_uses_these_routes_is_the_asset_studio_panel_and_only_five_of_them",
    ),
    "Other programs cannot reach any of it.": ("test_with_the_row_off_every_route_answers_404_and_none_is_listed",),
    "A job still running is ended and marked cancelled, and a program set to hear when jobs finish is told.": (
        "test_a_job_still_running_is_ended_and_kept_as_cancelled",
        "test_a_program_set_to_hear_is_told_and_your_jobs_templates_and_that_setting_stay",
    ),
    "Your jobs, your templates and that setting are kept, and come back when you turn this on.": (
        "test_a_program_set_to_hear_is_told_and_your_jobs_templates_and_that_setting_stay",
    ),
    "A ComfyUI that Thomas started can keep running, and after this Thomas cannot stop it, so close it yourself.": (
        "test_a_comfyui_thomas_started_can_keep_running_and_thomas_cannot_stop_it_after",
    ),
    "If you still have the Asset Studio page open, it goes on showing what it last showed until you press something.": (
        "test_an_open_page_keeps_what_it_showed_and_asks_for_nothing",
    ),
    "Then Boot, Refresh, Queue Render and Get Outputs each show a failure that does not say why, and Stop says a shutdown "
    "signal was sent when nothing was.": ("test_each_button_fails_without_saying_why_and_stop_says_it_worked",),
    "Reloaded, the page says Comfy is offline, even if ComfyUI is running.": (
        "test_reloaded_it_says_offline_with_comfyui_up_and_asks_once_for_each",
    ),
}
STOP_NOW = {
    "A program or page still waiting on a job or on ComfyUI gets no answer, and may need to ask again.": (
        "test_a_request_waiting_on_a_job_holds_the_stop_until_stop_now",
        "test_a_workflow_on_its_way_to_comfyui_goes_on_after_stop_now",
    ),
    "The job is ended and marked cancelled.": ("test_a_request_waiting_on_a_job_holds_the_stop_until_stop_now",),
    "A workflow already on its way to ComfyUI may still arrive.": (
        "test_a_workflow_on_its_way_to_comfyui_goes_on_after_stop_now",
    ),
}


def _shown(page: Any) -> str:
    """The panel's words, read through the window: ``innerText`` leaves out what is hidden."""
    return " ".join(page.locator(PANEL).inner_text().split())


def _ways_in(page: Any) -> int:
    """Buttons and links that name it. Settings may name it in the Plugins list, which is words and opens nothing."""
    return page.locator("a, button").filter(has_text=re.compile(r"asset studio|comfy", re.IGNORECASE)).count()


def _opened(page: Any, base: str) -> None:
    page.goto(f"{base}/classic?nav=studio", wait_until="domcontentloaded")
    page.wait_for_selector(PANEL, timeout=90_000)
    # A server with no model opens its first-run dialog over the page. You would close it, and it is not this row's.
    page.evaluate(
        "() => ['easySetupModal', 'easySetupBackdrop'].forEach((id) => document.getElementById(id)?.remove())"
    )
    # On opening it reads the status and tries a boot, one after the other, and a press before that ends is ignored.
    page.wait_for_function(
        """() => {
            const comfy = moduleEnsureRuntime().workbench.studio.comfy;
            return comfy.autoBootAttempted && !comfy.booting && !comfy.statusLoading;
        }"""
    )


def _press(page: Any, action: str, says: str) -> None:
    """Press a button and wait for what it says on screen. The page keeps the same words in a hidden log, so ask for sight."""
    page.click(f"[data-comfy-action='{action}']")
    page.get_by_text(says, exact=True).locator("visible=true").first.wait_for(state="visible")


def _walk(base: str, port: int, browser: Any) -> dict[str, Any]:
    """Row on, then off with the page open, each button pressed, the page reloaded, then on again."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport={"width": 1366, "height": 768})
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page = context.new_page()
    page.set_default_timeout(60_000)
    comfy_url = f"http://127.0.0.1:{port}"

    def row_asks() -> dict[str, int]:
        return {path.removeprefix(ROUTES_PREFIX): count for path, count in asked.items() if ROUTES_PREFIX in path}

    # On: everything the words say goes away is there first, so nothing below can be a page that never worked.
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector(f"{SIDEBAR} button:has-text('Marketplace')")
    seen["sidebar"] = page.eval_on_selector_all(f"{SIDEBAR} button", "(all) => all.map((button) => button.innerText)")
    page.goto(f"{base}/settings?embed=1", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    seen["ways_in_settings"] = _ways_in(page)
    _opened(page, base)
    seen["ways_in_the_page_itself"] = _ways_in(page) + page.locator("[data-nav-mode='studio']").count()
    page.fill("[data-comfy-server-url]", comfy_url)
    page.click("[data-comfy-action='status']")
    page.wait_for_function("() => moduleEnsureRuntime().workbench.studio.comfy.status.running === true")
    page.wait_for_selector(f"{PANEL} [data-comfy-iframe]", state="visible")
    seen["on"] = _shown(page)

    # Off, with the page still open.
    seen["pressed_off"] = context.request.post(f"{base}/api/plugins/thomas/{ROW}/off", data={}).json()["state"]
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["asks_open"] = dict(asked)
    seen["open"] = _shown(page)
    seen["frame_open"] = page.locator(f"{PANEL} [data-comfy-iframe]").is_visible()

    _press(page, "status", "Could not read Comfy status.")
    seen["after_refresh"] = _shown(page)
    page.fill("[data-comfy-workflow]", '{"1": {}}')
    _press(page, "queue_workflow", "Queue request failed.")
    page.fill("[data-comfy-prompt-id]", "p1")
    _press(page, "refresh_outputs", "Could not fetch outputs.")
    _press(page, "boot", "Comfy boot did not reach ready state.")
    _press(page, "shutdown", "Comfy Studio shutdown signal sent.")
    seen["stop_reached_comfy"] = not comfy_is_up(port)

    # Reloaded, as you would meet it.
    asked.clear()
    _opened(page, base)
    page.wait_for_timeout(500)
    seen["asks_loading"] = row_asks()
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["asks_reloaded"] = dict(asked)
    seen["reloaded"] = _shown(page)
    page.locator(PANEL).get_by_text(OFFLINE, exact=True).scroll_into_view_if_needed()
    seen["offline_on_screen"] = page.locator(PANEL).get_by_text(OFFLINE, exact=True).is_visible()
    page.fill("[data-comfy-server-url]", comfy_url)
    _press(page, "status", "Could not read Comfy status.")
    seen["reloaded_comfy_up"] = (_shown(page), comfy_is_up(port))

    # On again, with no reload.
    seen["pressed_on"] = context.request.post(f"{base}/api/plugins/thomas/{ROW}/on", data={}).json()["state"]
    page.click("[data-comfy-action='status']")
    page.wait_for_function("() => moduleEnsureRuntime().workbench.studio.comfy.status.running === true")
    seen["back"] = _shown(page)
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real page, for the tests below to read. Each step needs the one before it."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("asset-studio-page")
    port = free_port()
    comfy = subprocess.Popen([sys.executable, str(comfy_script(folder)), str(port)], cwd=folder)
    try:
        with pytest.MonkeyPatch.context() as env:
            # With this set, opening the page would start what it names, on the machine running the test.
            env.delenv("THOMAS_COMFYUI_BOOT_CMD", raising=False)
            env.delenv("THOMAS_DB_PATH", raising=False)
            env.delenv("THOMAS_SQLITE_PATH", raising=False)
            with serving(folder) as base, sync_playwright() as playwright:
                return _walk(base, port, playwright.chromium.launch(headless=True))
    finally:
        end_comfy(port)
        comfy.kill()
        comfy.wait()


def test_no_button_opens_the_page(walked: dict[str, Any]) -> None:
    assert [label for label in walked["sidebar"] if "studio" in label.lower() or "comfy" in label.lower()] == []
    assert walked["sidebar"], "no sidebar was read, so this proves nothing"
    assert walked["ways_in_settings"] == 0


def test_an_open_page_keeps_what_it_showed_and_asks_for_nothing(walked: dict[str, Any]) -> None:
    """The page does not loop, which the Marketplace page did, and an open one still shows a ComfyUI it is reading."""
    assert "Running" in walked["on"]
    assert walked["pressed_off"] == "off"
    assert [path for path in walked["asks_open"] if ROUTES_PREFIX in path] == []
    assert sum(walked["asks_open"].values()) < LOOPING
    assert walked["open"] == walked["on"]
    assert walked["frame_open"] is True


def test_each_button_fails_without_saying_why_and_stop_says_it_worked(walked: dict[str, Any]) -> None:
    """``_press`` waits for each message on screen. Only Stop's is false: the response is never read."""
    assert "Running" in walked["after_refresh"]
    assert "Could not read Comfy status." in walked["after_refresh"]
    assert walked["stop_reached_comfy"] is False


def test_reloaded_it_says_offline_with_comfyui_up_and_asks_once_for_each(walked: dict[str, Any]) -> None:
    assert walked["asks_loading"] == {"comfy/status": 1, "comfy/boot": 1}
    assert [path for path in walked["asks_reloaded"] if ROUTES_PREFIX in path] == []
    assert sum(walked["asks_reloaded"].values()) < LOOPING
    assert OFFLINE in walked["reloaded"]
    assert walked["offline_on_screen"] is True
    shown, comfy_up = walked["reloaded_comfy_up"]
    assert comfy_up is True
    assert "Offline" in shown
    assert OFFLINE in shown


def test_turned_on_again_the_open_page_works_with_no_reload(walked: dict[str, Any]) -> None:
    assert walked["pressed_on"] == "active"
    assert "Running" in walked["back"]


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    with PROFILE_PATH.open("rb") as handle:
        row = next(row for row in tomllib.load(handle)["row"] if row["id"] == ROW)
    assert row["off_means"] == " ".join(OFF_MEANS)
    assert row["stop_now"] == " ".join(STOP_NOW)

    proofs = "".join(
        (ROOT / "tests" / name).read_text(encoding="utf-8") for name in (OFF_TEST, JOBS_TEST, Path(__file__).name)
    )
    for sentence, tests in {**OFF_MEANS, **STOP_NOW}.items():
        for test in tests:
            assert f"def {test}(" in proofs, sentence
