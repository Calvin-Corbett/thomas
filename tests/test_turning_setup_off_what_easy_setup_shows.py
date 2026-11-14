"""What the setup row's words say Easy Setup does with the row off, read from a real window.

These are the words of ``thomas.server.rows.setup`` for the pages of ``thomas.server.routes.setup_aiohttp``. Easy Setup is
a part of the older full page, so it lives in ``easy_setup_connection_flow.js`` and ``007_easy_setup_onboarding_05.js``, and
it opens only where that page is in the frame. The walk runs against a stand-in for Ollama, on a computer that is fixed
here, so it says the same on any machine and pulls nothing. A repair is counted and never run, because it changes this
computer.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server.proof.selection import select

WINDOW = {"width": 1366, "height": 768}
WORDS = next(row for row in ROWS if row.id == "setup").config["words"]
# Each takes you into the older full page, in a frame, and a new install shows Easy Setup over it.
OVER_THESE_PAGES = ("Virtual Office", "Canvas", "Channels", "Token Economy", "Marketplace")
ASKED = ("/api/setup/", "/api/local/recommendations", "/api/local/sync", "/api/local/background", "/api/local/pull")
OPEN = "() => document.getElementById('easySetupModal')?.classList.contains('active')"

_SERVE = """\
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.models import local_recommendations
from thomas.server import app_core

memory, address_at = sys.argv[1:]
installed = []
_run = subprocess.run
_which = shutil.which
hardware = {"cpu": {"cores": 16}, "memory": {"total_gb": 64.0}, "gpu": {"max_vram_gb": 24.0}, "device_tier": "power"}


def run(command, *args, **kwargs):
    if "repair.ps1" in str(command):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    return _run(command, *args, **kwargs)


subprocess.run = run
shutil.which = lambda name, *args, **kwargs: name if name.startswith("ollama") else _which(name, *args, **kwargs)
local_recommendations.detect_local_hardware_profile = lambda: hardware


async def tags(request):
    return web.json_response({"models": [{"name": name} for name in installed]})


async def pull(request):
    installed.append((await request.json())["name"])
    return web.Response(text=json.dumps({"status": "success"}) + "\\n")


async def generate(request):
    return web.json_response({"response": json.dumps({"tool_ready": True})})


async def models(request):
    return web.json_response({"object": "list", "data": [{"id": "dummy", "object": "model"}]})


async def chat(request):
    message = {"role": "assistant", "content": "ok"}
    return web.json_response({"object": "chat.completion", "choices": [{"index": 0, "message": message}]})


async def serve():
    ollama = web.Application()
    ollama.add_routes([web.get("/api/tags", tags), web.get("/v1/models", models), web.post("/api/pull", pull)])
    ollama.add_routes([web.post("/api/generate", generate), web.post("/v1/chat/completions", chat)])
    stand_in = TestServer(ollama)
    await stand_in.start_server()
    local = ModelConfig(name="local", model="dummy", base_url=str(stand_in.make_url("/v1")))
    config = AppConfig(models={"local": local}, default_model="local", memory=MemoryConfig(root=memory))
    server = TestServer(app_core.create_app(config))
    await server.start_server()
    Path(address_at).write_text(str(server.make_url("/")).rstrip("/") + "\\n", encoding="utf-8")
    await asyncio.Event().wait()


asyncio.run(serve())
"""


def _opens_over(browser: Any, base: str, name: str) -> int:
    """Waits for Easy Setup to come up over that page, in a window of its own. Returns Chat's Settings buttons, on the way."""
    context = browser.new_context(viewport=WINDOW)
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector(".bt-tab")  # a press before the tabs are up lands in a frame that then stays hidden
    chat = page.locator("#tc-settings").count()
    page.click(f"button:has-text('{name}')")
    page.frame_locator("iframe[src*='classic']").locator("#easySetupModal.active").wait_for(state="visible")
    context.close()
    return chat


def _walk(base: str, browser: Any) -> dict[str, Any]:
    """A new install, as you would meet it. Each step needs the one before it."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))

    def press(state: str) -> None:
        assert context.request.post(f"{base}/api/plugins/thomas/setup/{state}", data={}).status == 200

    def opened() -> None:
        page.goto(f"{base}/classic", wait_until="domcontentloaded")
        page.wait_for_function(OPEN)
        page.wait_for_timeout(500)

    def status(where: str = "#easySetupConnectionStatus") -> str:
        return page.locator(where).inner_text().strip()

    def grey() -> bool:
        return page.locator("#easySetupNextBtn").is_disabled()

    def connect_and_test(until: str) -> str:
        page.click("#easySetupTestConnectionBtn")
        page.wait_for_function(
            "(until) => new RegExp(until).test(document.getElementById('easySetupConnectionStatus').innerText)",
            arg=until,
            timeout=180_000,  # a busy machine took over a minute to check a model that answers at once
        )
        return status()

    # With the row off, because then nothing has to wait for a look at this computer.
    press("off")
    seen["over"] = {name: _opens_over(browser, base, name) for name in OVER_THESE_PAGES}
    press("on")
    page = context.new_page()
    page.set_default_timeout(60_000)

    # On first, so nothing below can be a page that never worked.
    opened()
    seen["hint_on"], seen["grey_on"] = status("#easySetupRecommendedHint"), grey()

    press("off")
    opened()
    seen["hint_off"], seen["grey_off"] = status("#easySetupRecommendedHint"), grey()
    seen["needed_off"] = page.evaluate(
        """() => ['codex', 'manual'].flatMap((path) => buildEasySetupDependencyPlan(null, path).filter((dep) => dep.required))"""
    )
    page.click("#easySetupPathGrid [data-path='local']")
    page.click("#easySetupNextBtn")
    before = status()
    asked.clear()
    page.click("#easySetupAutoRepairBtn")
    page.wait_for_timeout(1500)
    seen["auto_repair"] = (asked["/api/setup/repair"], before == status())
    seen["tested_off"] = connect_and_test("No hardware|failed")
    page.click("#easySetupNextBtn")
    page.wait_for_function("() => document.getElementById('easySetupProgressText').innerText === 'Step 3 of 5'")
    seen["pills_off"] = page.locator(".easy-setup-dep-pill").all_inner_texts()
    page.click("#easySetupApproveAllBtn")
    page.wait_for_function("() => /failed/.test(document.getElementById('easySetupDependencyStatus').innerText)")
    seen["approved_off"], seen["grey_at_three"] = status("#easySetupDependencyStatus"), grey()
    asked.clear()
    page.wait_for_timeout(10_000)
    seen["asked_in_ten_seconds"] = sum(count for path, count in asked.items() if path.startswith(ASKED))

    press("on")
    opened()
    seen["pills_on"] = page.locator(".easy-setup-dep-pill").all_inner_texts()
    page.click("#easySetupBackBtn")
    seen["tested_on"] = connect_and_test("Verified|failed")

    press("off")
    seen["tested_already_open"] = connect_and_test("sync failed")

    opened()
    page.click("#easySetupDismissBtn")
    page.wait_for_function("() => !document.getElementById('easySetupModal').classList.contains('active')")
    page.wait_for_timeout(500)
    press("on")
    asked.clear()
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    seen["back_after_skip"] = page.evaluate(OPEN)
    seen["asked_after_skip"] = sum(count for path, count in asked.items() if path.startswith(ASKED))
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real page, for the tests below to read."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with serving(tmp_path_factory.mktemp("setup-page"), script=_SERVE) as base, sync_playwright() as playwright:
        return _walk(base, playwright.chromium.launch(headless=True))


def test_a_new_install_shows_easy_setup_over_the_pages_the_words_name(walked: dict[str, Any]) -> None:
    assert walked["over"] == dict.fromkeys(OVER_THESE_PAGES, 1)
    assert all(name in WORDS["about"] for name in OVER_THESE_PAGES)


def test_chat_still_opens_and_easy_setup_says_it_could_not_check(walked: dict[str, Any]) -> None:
    assert walked["hint_on"].startswith("Recommended: ")
    assert walked["grey_on"] is False
    assert walked["hint_off"] == "Bootstrap check failed: Setup bootstrap failed (404)"
    assert walked["hint_off"] in WORDS["off_means"]
    assert walked["grey_off"] is True  # nothing is chosen for you, so Continue waits for you to choose


def test_two_paths_need_nothing_from_this_row_and_auto_repair_shows_nothing(walked: dict[str, Any]) -> None:
    assert walked["needed_off"] == []
    assert walked["auto_repair"] == (1, True)


def test_local_ollama_cannot_be_finished_and_the_page_blames_something_else(walked: dict[str, Any]) -> None:
    """Exactly this and no more. If the page learns to say why, this fails and the words must change."""
    assert walked["tested_off"].endswith(
        "No hardware-recommended local models for this device tier. Continuing with local profile only."
    )
    assert walked["pills_off"] == ["Required", "Required"]
    assert walked["pills_on"] == ["Ready", "Ready"]  # the same stand-in, so Required above was not true
    assert walked["approved_off"] == "Repair call failed. Remediation: run repair from command line and retry."
    assert walked["grey_at_three"] is True


def test_no_page_asks_again_and_again_with_the_row_off(walked: dict[str, Any]) -> None:
    assert walked["asked_in_ten_seconds"] == 0


def test_back_on_a_reload_and_connect_and_test_download_the_models(walked: dict[str, Any]) -> None:
    assert re.search(r"Verified (\d)/\1 local models\. Pulled \1 missing\.", walked["tested_on"]), walked["tested_on"]


def test_an_easy_setup_already_open_blames_ollama(walked: dict[str, Any]) -> None:
    said = "Local model sync failed (404) Remediation: ensure Ollama is running and retry."
    assert walked["tested_already_open"] == said


def test_skip_for_now_does_not_come_back_by_itself(walked: dict[str, Any]) -> None:
    """Which is also why a Thomas past Easy Setup asks these routes for nothing."""
    assert walked["back_after_skip"] is False
    assert walked["asked_after_skip"] == 0


def test_the_pages_that_call_these_routes_are_the_ones_the_words_cover() -> None:
    """A new caller has to be read before these words can stay, so it fails here first.

    The Tools Console is on the older full page only, whose button has no size in the frame, so the words leave it out.
    ``040_model_setup_settings_01.js`` asks for recommendations for a line no page has, as the test below shows.
    """
    web = ROOT / "thomas" / "server" / "web"
    pages = (*web.rglob("*.js"), *web.rglob("*.html"))
    calling = sorted(path.name for path in pages if any(route in path.read_text(encoding="utf-8") for route in ASKED))

    assert calling == [
        "007_easy_setup_onboarding_05.js",
        "015_debug_dock.js",
        "040_model_setup_settings_01.js",
        "easy_setup_connection_flow.js",
    ]


def test_the_power_pc_line_that_asks_for_recommendations_is_on_no_page() -> None:
    """So its caller returns before it asks. If the line comes back, the words have a page to add."""
    web = ROOT / "thomas" / "server" / "web"
    places = [*web.glob("*.html"), *(web / "js" / "templates").glob("*.js")]

    assert len(places) > 5  # an empty list would pass below
    assert [path.name for path in places if "settingAdvPowerPcBadge" in path.read_text(encoding="utf-8")] == []


@pytest.mark.parametrize("script", ["easy_setup_connection_flow.js", "007_easy_setup_onboarding_05.js"])
def test_a_change_to_the_page_runs_what_holds_its_words(script: str) -> None:
    """A check finds this file by those names in its text, so losing one would leave the page free to drift from the words."""
    chosen = select(ROOT, [f"thomas/server/web/js/runtime/{script}"]).files
    assert "tests/test_turning_setup_off_what_easy_setup_shows.py" in chosen
