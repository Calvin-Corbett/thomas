"""The Improve Thomas window, in a real browser, as the project_queue row goes off and on.

The row is ``thomas.server.rows.project_queue`` and the window is ``self_edit_controls.js``, opened from the Improve Thomas
button in the project menu of ``chat_composer_panels.js`` inside Build. Those names are how a check finds this file when
one of them changes. The row's words say what you see, so this reads what a window shows on a real server, presses
what you would press, and counts what the page asks for.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import _SERVE, serving
from tests.row_proof_fixture import ROOT
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server.proof.selection import select

QUEUE = "/api/self/projects/queue"
PLANNER = "/api/self/projects/queue/planner"
LIST = "/api/self/projects"
TEN_SECONDS = 10_000
WINDOW = {"width": 1366, "height": 768}
DIALOG = "#tc-self-edit-dialog"


def _words(place: object, selector: str) -> str:
    return " ".join(place.locator(selector).first.inner_text().split())  # type: ignore[attr-defined]


def _walk(base: str, browser: Any) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    context.set_default_timeout(60_000)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page = context.new_page()

    def open_the_window() -> Any:
        """Build, then the window itself. Improve Thomas now selects Thomas as the project instead of opening this window
        (tests/test_improve_thomas_selects_thomas.py); the projects list and the switch move onto the Build page next."""
        page.goto(f"{base}/", wait_until="load")
        # A click before the page has bound its buttons does nothing, and a busy machine can be that slow, so press again.
        for attempt in range(12):
            page.locator("#tc-mode-switch").get_by_text("Build").first.click()
            try:
                page.locator("iframe.bt-doc").first.wait_for(state="attached", timeout=5_000)
                break
            except PlaywrightTimeout:
                assert attempt < 11, "Build never opened"
        frame = page.frame_locator("iframe.bt-doc").first
        frame.locator("#tc-code-project-btn").wait_for()  # Build's scripts are in, self_edit_controls.js among them
        frame.locator("body").evaluate(
            "() => new Promise((done, fail) => { const start = Date.now(); (function look() {"
            " if (window.ThomasSelfEdit) { window.ThomasSelfEdit.open(); done(); }"
            " else if (Date.now() - start > 30000) fail(new Error('self_edit_controls.js never loaded'));"
            " else setTimeout(look, 100); })(); })"
        )
        frame.locator(f"{DIALOG} [data-self-queue]:not(:has-text('Loading planned improvements'))").wait_for()
        # The list of Thomas projects asks again about once a second while it says it is checking, and that is not this
        # row's, so it is let settle before anything is read or counted.
        frame.locator(f"{DIALOG} [data-self-projects]:has-text('Thomas project'):not(:has-text('Checking'))").wait_for()
        return frame

    asked.clear()
    window = open_the_window()
    seen["on_text"] = _words(window, DIALOG)
    seen["on_asked"] = [asked[QUEUE], asked[PLANNER]]
    seen["on_switch"] = window.locator(f"{DIALOG} [data-planner-enabled]").count()

    # A window that was open before the press: it keeps what it read until you open it again, and its switch fails.
    context.request.post(f"{base}/api/plugins/thomas/project_queue/off")
    seen["still_open_text"] = _words(window, DIALOG)
    window.locator(f"{DIALOG} [data-planner-enabled]").click()
    window.locator(f"{DIALOG} [data-planner-error]:not(:empty)").wait_for()
    seen["still_open_error"] = _words(window, f"{DIALOG} [data-planner-error]")
    seen["still_open_checked"] = window.locator(f"{DIALOG} [data-planner-enabled]").is_checked()

    asked.clear()
    window = open_the_window()
    seen["off_text"] = _words(window, DIALOG)
    seen["off_part"] = _words(window, f"{DIALOG} [data-self-queue]")
    seen["off_asked"] = [asked[QUEUE], asked[PLANNER]]
    seen["off_start_button"] = window.locator(f"{DIALOG} button[type='submit']").is_enabled()
    seen["off_answers"] = [
        context.request.get(f"{base}{QUEUE}").status,
        context.request.get(f"{base}{PLANNER}").status,
        context.request.post(f"{base}{QUEUE}", data={}).status,
        context.request.put(f"{base}{PLANNER}", data={"enabled": False}).status,
    ]
    seen["list_still_answers"] = context.request.get(f"{base}{LIST}").status
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["asked_in_ten_seconds"] = [asked[QUEUE], asked[PLANNER], asked[LIST]]

    context.request.post(f"{base}/api/plugins/thomas/project_queue/on")
    window = open_the_window()
    seen["on_again_text"] = _words(window, DIALOG)
    seen["on_again_switch"] = window.locator(f"{DIALOG} [data-planner-enabled]").count()
    return seen


# The catalog of Thomas projects is the checkout the code runs from, so on your own Thomas the page would list your real
# projects and never say none is going. The server this walk starts reads a catalog of its own, as other tests of it do.
OWN_CATALOG = """\nimport sys
from pathlib import Path

from thomas.server import thomas_project

_catalog = Path(sys.argv[1]).parent / "catalog"
_catalog.mkdir(exist_ok=True)
thomas_project._catalog_root = lambda: _catalog
"""


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with (
        serving(tmp_path_factory.mktemp("queue-page"), script=OWN_CATALOG + _SERVE) as base,
        sync_playwright() as playwright,
    ):
        return _walk(base, playwright.chromium.launch(headless=True))


def test_with_the_row_on_the_window_shows_planned_improvements_and_its_switch(walked: dict[str, Any]) -> None:
    assert "Planned improvements" in walked["on_text"]
    assert "Plan and start automatic improvements" in walked["on_text"]
    assert "0 running" in walked["on_text"] and "0 queued" in walked["on_text"]
    assert walked["on_switch"] == 1


def test_the_window_asks_for_the_queue_and_the_switch_once_each_time_it_opens(walked: dict[str, Any]) -> None:
    assert walked["on_asked"] == [1, 1]
    assert walked["off_asked"] == [1, 1]


def test_with_the_row_off_the_planned_improvements_part_is_a_line_of_technical_text(walked: dict[str, Any]) -> None:
    assert "Planned improvements" not in walked["off_text"]
    assert "Plan and start automatic improvements" not in walked["off_text"]
    assert "JSON" in walked["off_part"], walked["off_part"]
    assert "off" not in walked["off_part"].casefold().split(), walked["off_part"]


def test_with_the_row_off_the_rest_of_the_window_carries_on(walked: dict[str, Any]) -> None:
    assert "No Thomas project is going right now." in walked["off_text"]
    assert walked["off_start_button"] is True
    assert walked["list_still_answers"] == 200


def test_with_the_row_off_every_request_for_the_queue_is_told_there_is_no_such_address(walked: dict[str, Any]) -> None:
    assert walked["off_answers"] == [404, 404, 404, 404]


def test_with_the_row_off_the_page_asks_nothing_on_its_own(walked: dict[str, Any]) -> None:
    """It asks when the window opens and again only when you press the switch, so ten seconds alone is silence."""
    assert walked["asked_in_ten_seconds"] == [0, 0, 0]


def test_a_window_open_when_it_goes_off_keeps_what_it_read_until_you_open_it_again(walked: dict[str, Any]) -> None:
    assert walked["still_open_text"] == walked["on_text"]


def test_the_switch_in_a_window_open_when_it_goes_off_flips_back_with_the_same_technical_text(
    walked: dict[str, Any],
) -> None:
    assert "JSON" in walked["still_open_error"], walked["still_open_error"]
    assert walked["still_open_checked"] is True


def test_turned_back_on_the_window_shows_the_queue_again_with_no_restart(walked: dict[str, Any]) -> None:
    assert "Planned improvements" in walked["on_again_text"]
    assert walked["on_again_switch"] == 1


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/web/js/self_edit_controls.js",
        "thomas/server/web/js/chat_composer_panels.js",
        "thomas/server/rows/project_queue.py",
    ],
)
def test_a_change_to_the_window_or_the_row_runs_this_walk(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_the_improve_thomas_window_with_its_queue_off.py" in chosen
