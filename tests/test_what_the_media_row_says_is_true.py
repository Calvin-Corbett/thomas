"""The media row's words, each held by what a real window shows on a real server.

One walk through Chat, with a stand-in for the model that holds its thread until told, because a real one needs a GPU and
a download. Only Chat calls these routes, so only Chat is walked, with its requests counted while the row is off. Each
test names the sentence it holds, so a change to the words has to come through here.
``thomas.server.rows.media`` and ``thomas.server.routes.media_generation_routes`` are named here because this file imports
neither, and those names are how a check finds it.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests import row_page_fixture
from tests.media_row_fixture import A_MODEL_THAT_WAITS
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok

WINDOW = {"width": 1500, "height": 950}
SIDEBAR = "#tc-workspaces"
WORDS = next(row for row in ROWS if row.id == "media").config["words"]
OFF_MEANS = WORDS["off_means"]
CAME_FROM_THE_ROUTE = "could not start: Unexpected non-whitespace character after JSON"


def _create(page: Any, medium: str, words: str) -> None:
    page.fill("#tc-input", words)
    page.click("#tc-attach-btn")
    page.click(f"[data-create-action={medium}]")


def _says(page: Any, words: str) -> str:
    page.wait_for_function("(words) => document.getElementById('tc-thread').innerText.includes(words)", arg=words)
    return " ".join(page.locator("#tc-thread").inner_text().split())


def _library(page: Any) -> str:
    page.click(f"{SIDEBAR} button:has-text('Library')")
    frame = page.wait_for_selector("iframe[src*='/my-stuff']").content_frame()
    # The page lists what it can at once, and what Thomas made comes a moment later, from a slower scan.
    frame.wait_for_function("() => document.body.innerText.includes('A third bus')")
    return " ".join(frame.evaluate("() => document.body.innerText").split())


def _walk(base: str, folder: Path, browser: Any) -> dict[str, Any]:
    """Each step needs the one before it, as you would meet them."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page = context.new_page()
    page.set_default_timeout(60_000)

    def press(word: str) -> Any:
        return context.request.post(f"{base}/api/plugins/thomas/media/{word}", data={}).json()

    def asks_in_ten_seconds() -> int:
        asked.clear()
        context.pages[-1].wait_for_timeout(10_000)
        return sum(count for path, count in asked.items() if path.startswith("/api/media"))

    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("#tc-input")

    # A job, then off with its page open.
    _create(page, "image", "An orange bus")
    _says(page, "Loading the stand-in model")
    seen["off"] = press("off")
    seen["open_after_off"] = _says(page, "Reconnecting to image generation status")
    seen["asks_while_a_stopped_job_is_open"] = asks_in_ten_seconds()
    page.click("#tc-send")
    seen["after_pressing_stop"] = _says(page, "Stopping")
    # The reload button, which Ctrl+R and F5 press too. On the first Chat tab it does not rebuild the page.
    page.click("#bt-reload")
    page.wait_for_timeout(2000)
    seen["after_the_reload_button"] = _says(page, "Reconnecting to image generation status")
    page.close()
    # What you get when you open Thomas again.
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("#tc-input")
    seen["opened_again"] = _says(page, "Stopped")
    seen["asks_once_opened_again"] = asks_in_ten_seconds()

    # Off, asking for one both ways the page offers.
    _create(page, "image", "A green bus")
    seen["refused"] = _says(page, f"Create image {CAME_FROM_THE_ROUTE}")
    seen["box_after_refusal"] = page.input_value("#tc-input")
    _create(page, "music", "")
    seen["chip"] = page.locator("#tc-media-lane-chip").inner_text()
    page.fill("#tc-input", "A tune")
    page.keyboard.press("Enter")
    seen["refused_after_arming"] = _says(page, f"Create music {CAME_FROM_THE_ROUTE}")
    seen["box_after_arming"] = page.input_value("#tc-input")
    seen["asks_after_refusal"] = asks_in_ten_seconds()
    page.locator("#tc-media-lane-chip button").click()

    # On with the page open: a job off stopped, and a setup box off reached first.
    seen["back_on"] = press("on")
    _create(page, "image", "A second bus")
    seen["waiting_behind_the_old_model"] = _says(page, "Starting the background worker")
    press("off")
    _says(page, "Reconnecting to image generation status")
    press("on")
    seen["interrupted"] = _says(page, "The image generation was interrupted before delivery.")
    _create(page, "video", "A clip")
    page.wait_for_selector("#tc-media-setup:not([hidden])")
    press("off")
    page.fill("#tc-media-key", "not-a-real-key")
    page.click("[data-media-provider=api]")
    page.wait_for_function("() => document.querySelector('.tc-media-error').textContent.includes('JSON')")
    seen["setup_box"] = page.locator(".tc-media-error").inner_text()
    page.click(".tc-media-close")
    press("on")
    seen["lanes_after_the_box"] = context.request.get(f"{base}/api/media/lanes").json()["lanes"]

    # What is finished stays.
    (folder / "let-go").write_text("go", encoding="utf-8")
    _create(page, "image", "A third bus")
    page.wait_for_selector("#tc-thread .tc-media-deliverable img")
    press("off")
    page.click("#bt-reload")
    page.wait_for_selector("#tc-thread .tc-media-deliverable img")
    page.wait_for_function("() => document.querySelector('#tc-thread .tc-media-deliverable img').naturalWidth > 0")
    seen["image_width_off"] = page.evaluate(
        "() => document.querySelector('#tc-thread .tc-media-deliverable img').naturalWidth"
    )
    seen["library_off"] = _library(page)
    press("on")
    seen["lanes_at_the_end"] = context.request.get(f"{base}/api/media/lanes").json()["lanes"]
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("media-page")
    lanes = folder / "memory" / ".thomas" / "media_lanes.json"
    lanes.parent.mkdir(parents=True)
    lanes.write_text('{"image": "local"}', encoding="utf-8")
    with pytest.MonkeyPatch.context() as change:
        change.setattr(row_page_fixture, "_SERVE", A_MODEL_THAT_WAITS + row_page_fixture._SERVE)
        with serving(folder) as base, sync_playwright() as playwright:
            return _walk(base, folder, playwright.chromium.launch(headless=True))


def test_asking_for_one_says_it_could_not_start_and_never_says_why(walked: dict[str, Any]) -> None:
    assert "none of them can start" in OFF_MEANS
    assert (
        "saying it could not start, followed by an error about JSON, and nothing says this is turned off" in OFF_MEANS
    )
    for refused in (walked["refused"], walked["refused_after_arming"]):
        assert CAME_FROM_THE_ROUTE in refused
        assert "turned off" not in refused
    assert walked["chip"] == "Create music"


def test_your_words_stay_in_the_box(walked: dict[str, Any]) -> None:
    assert "Your words stay in the box." in OFF_MEANS
    assert (walked["box_after_refusal"], walked["box_after_arming"]) == ("A green bus", "A tune")


def test_a_setup_box_already_open_fails_the_same_way_and_keeps_nothing(walked: dict[str, Any]) -> None:
    assert "A setup box already open fails with the same error and does not keep the key you typed." in OFF_MEANS
    assert "after JSON" in walked["setup_box"]
    assert walked["lanes_after_the_box"]["video"]["configured"] is False


def test_what_you_made_and_chose_stays(walked: dict[str, Any]) -> None:
    assert "What you already made stays in your chats and Library" in OFF_MEANS
    assert "your choice of model or key stays" in OFF_MEANS
    assert walked["image_width_off"] == 64
    assert "Create image: A third bus" in walked["library_off"]
    assert walked["lanes_at_the_end"]["image"]["configured"] is True


def test_off_takes_no_time_and_a_page_with_a_job_keeps_saying_reconnecting(walked: dict[str, Any]) -> None:
    assert "is stopped straight away" in OFF_MEANS
    assert "goes on saying Reconnecting, and its Stop button only says Stopping" in OFF_MEANS
    assert walked["off"]["state"] == "off"
    assert "Reconnecting to image generation status" in walked["open_after_off"]
    assert "Stopping" in walked["after_pressing_stop"]
    assert "Reconnecting to image generation status" in walked["after_pressing_stop"]


def test_opening_thomas_again_shows_it_as_stopped_and_on_says_it_was_interrupted(walked: dict[str, Any]) -> None:
    assert "until you open Thomas again, which shows it as Stopped" in OFF_MEANS
    assert "or turn this back on, which says it was interrupted. The reload button may not clear it." in OFF_MEANS
    assert "Stopping" in walked["after_the_reload_button"]
    assert "Stopped" in walked["opened_again"]
    assert "Media generation interrupted" in walked["opened_again"]
    assert walked["back_on"]["state"] == "active"
    assert "The image generation was interrupted before delivery." in walked["interrupted"]


def test_none_of_a_stopped_job_reaches_you(walked: dict[str, Any]) -> None:
    assert "none of it reaches you" in OFF_MEANS
    assert "An orange bus" not in walked["library_off"]
    assert "A second bus" not in walked["library_off"]


def test_anything_new_on_a_local_model_waits_behind_what_off_could_not_end(walked: dict[str, Any]) -> None:
    assert "anything new you create with one waits behind them" in OFF_MEANS
    assert "Starting the background worker" in walked["waiting_behind_the_old_model"]


def test_no_page_loops_with_the_row_off(walked: dict[str, Any]) -> None:
    """One that asks many times a second can freeze a window, and a switch on the Plugins page must not be able to.

    A job that was running goes on being asked for, slower each time, up to once in 30 seconds. That is the page waiting
    for the job's answer, and it ends with the row back on or a new window.
    """
    assert 1 <= walked["asks_while_a_stopped_job_is_open"] <= 5
    assert walked["asks_once_opened_again"] == 0
    assert walked["asks_after_refusal"] == 0


def test_only_chat_calls_these_routes() -> None:
    """The row's words name only Chat. If another page starts calling these routes, they have to change, and so does the
    walk above. The page's own file is in the answer, so a search that found nothing at all cannot pass.
    """
    folders = (ROOT / "thomas" / "server" / "web", ROOT / "extensions")
    pages = (path for folder in folders for path in folder.rglob("*") if path.suffix in {".html", ".js", ".ts", ".tsx"})
    calling = [path.name for path in pages if "api/media/" in path.read_text(encoding="utf-8", errors="replace")]

    assert calling == ["chat_media_generation.js"]
