"""The Plugins page in Settings, in a real browser: the sets first, the long list folded away, and the Pause control.

The page is ``thomas/server/web/settings.plugins-panel.js`` with ``thomas/server/web/settings.plugins-sets.js``. It asks
``thomas.server.rows.plugin_sets`` for the sets and, for the Pause control, for routes that are built beside it and are
stood in for here by the browser. This walks a real scratch server with every plugin on, on a home and a project catalog
of its own, and counts what the page asks for.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import _SERVE, serving
from tests.row_proof_fixture import ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server.ready_made_sets import read_sets

PAGE = "/settings?section=plugins"
STATUS = "/api/plugins/thomas"
SETS = "/api/plugins/sets"
PAUSE = "/api/thomas/pause"
TEN_SECONDS = 10_000
WINDOW = {"width": 1280, "height": 900}
ADVANCED = "Advanced: choose each plugin yourself"
ALL = [row.id for row in ROWS]
REQUIRED = {row.id for row in ROWS if row.config["required"]}
GROUPS = read_sets()["groups"]

# The project catalog is the checkout the code runs from, so the page would list your real projects. The server this walk
# starts reads a catalog of its own, as the walks of other pages do.
OWN_CATALOG = """\nimport sys
from pathlib import Path

from thomas.server import thomas_project

_catalog = Path(sys.argv[1]).parent / "catalog"
_catalog.mkdir(exist_ok=True)
thomas_project._catalog_root = lambda: _catalog
"""


def _words(place: Any, selector: str | None = "#plugins") -> str:
    found = place.locator(selector) if selector else place
    return " ".join(found.first.inner_text().split())


def _card(page: Any, title: str) -> Any:
    return page.locator("#plugins .plugin-set-card").filter(has=page.get_by_role("heading", name=title, exact=True))


def _rows_shown(page: Any) -> int:
    return page.locator("#plugins .plugin-row:visible").count()


def _stand_in_for_pause(page: Any, calls: list[str]) -> None:
    """Lane P builds the routes. This answers as they will: paused, since, reason and how many runs are still finishing."""
    state = {"paused": False}

    def answer(route: Any) -> None:
        request = route.request
        calls.append(f"{request.method} {urlsplit(request.url).path}")
        if request.method == "POST":
            state["paused"] = request.url.endswith("/pause")
        body = {"paused": state["paused"], "since": 1.0 if state["paused"] else None, "reason": "", "still_running": 2}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/thomas/pause", answer)
    page.route("**/api/thomas/resume", answer)


def _status(context: Any, base: str) -> dict[str, dict[str, Any]]:
    report = context.request.get(f"{base}{STATUS}").json()
    return {row["id"]: row for row in report["rows"]}


def _walk(base: str, browser: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    context.set_default_timeout(60_000)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page = context.new_page()
    pause_calls: list[str] = []

    # A server with no pause route, as an older Thomas is: the page hides the control and says nothing. This server has
    # the route now, so the browser answers 404 for it.
    page.route("**/api/thomas/pause", lambda route: route.fulfill(status=404, body="not found"))
    asked.clear()
    page.goto(f"{base}{PAGE}", wait_until="load")
    page.locator("#plugins .plugin-set-card").first.wait_for()
    seen["no_pause_text"] = _words(page)
    seen["no_pause_buttons"] = page.locator("#plugins .plugins-pause:visible").count()
    page.wait_for_timeout(TEN_SECONDS)
    seen["quiet_asked"] = {
        path: count for path, count in asked.items() if path.startswith(("/api/plugins", "/api/thomas"))
    }
    seen["quiet_total"] = sum(asked.values())

    # Now the control is there.
    page.unroute("**/api/thomas/pause")
    _stand_in_for_pause(page, pause_calls)
    page.reload(wait_until="load")
    page.locator("#plugins .plugins-pause:visible").wait_for()
    seen["working_text"] = _words(page, "#plugins .plugins-pause")
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["pause_asked_in_ten_seconds"] = asked[PAUSE]
    seen["status_asked_in_ten_seconds"] = asked[STATUS]
    page.get_by_role("button", name="Pause", exact=True).click()
    page.locator("#plugins .plugins-pause:has-text('paused')").wait_for()
    seen["paused_text"] = _words(page, "#plugins .plugins-pause")
    seen["paused_buttons"] = page.locator("#plugins .plugins-pause button:visible").all_inner_texts()
    page.get_by_role("button", name="Resume", exact=True).click()
    page.locator("#plugins .plugins-pause:has-text('working')").wait_for()
    seen["pause_calls"] = [call for call in pause_calls if call.startswith("POST")]

    # The default view.
    page.reload(wait_until="load")
    page.locator("#plugins .plugin-set-card").first.wait_for()
    seen["cards"] = page.locator("#plugins .plugin-set-title").all_inner_texts()
    seen["default_rows_shown"] = _rows_shown(page)
    seen["default_text"] = _words(page)
    seen["advanced_button"] = page.get_by_role("button", name=ADVANCED).count()
    seen["advanced_closed"] = page.get_by_role("button", name=ADVANCED).get_attribute("aria-expanded")

    # Advanced opens the list under its headings, and the choice lasts for this tab's session only.
    page.get_by_role("button", name=ADVANCED).click()
    page.locator("#plugins .plugin-row:visible").first.wait_for()
    seen["open_rows_shown"] = _rows_shown(page)
    seen["group_titles"] = page.locator("#plugins .plugin-group:visible .plugin-group-title").all_inner_texts()
    seen["rows_under_groups"] = page.locator("#plugins .plugin-group:visible .plugin-row").count()
    seen["required_lock"] = page.locator("#plugins .plugin-row:has-text('Always on')").count()
    page.reload(wait_until="load")
    page.locator("#plugins .plugin-row:visible").first.wait_for()
    seen["remembered_open"] = _rows_shown(page) > 0
    other = browser.new_context(viewport=WINDOW)
    other_page = other.new_page()
    other_page.goto(f"{base}{PAGE}", wait_until="load")
    other_page.locator("#plugins .plugin-set-card").first.wait_for()
    seen["new_session_open"] = _rows_shown(other_page) > 0
    other.close()
    page.get_by_role("button", name=ADVANCED).click()
    seen["closed_again"] = _rows_shown(page)

    # Applying the smallest set: it asks first, then does it, and says what happened.
    before = _status(context, base)
    on_now = [row_id for row_id, row in before.items() if row["enabled"] and row_id not in REQUIRED | {"plugin_sets"}]
    smallest = next(item for item in read_sets()["sets"] if item["id"] == "just_chat_and_build")
    to_turn_off = [row_id for row_id in on_now if row_id not in smallest["rows"]]
    seen["expect_off"] = len(to_turn_off)
    card = _card(page, "Just chat and build")
    card.get_by_role("button", name="Apply").click()
    seen["asks"] = _words(card, None)
    seen["unchanged_while_asking"] = len([row for row in _status(context, base).values() if row["state"] == "active"])
    card.get_by_role("button", name="Cancel").click()
    seen["cancelled_text"] = _words(card, None)
    card.get_by_role("button", name="Apply").click()
    asked.clear()
    card.get_by_role("button", name="Go").click()
    card.locator(".plugin-set-note:has-text('Done.')").wait_for()
    seen["result"] = _words(card, None)
    after = _status(context, base)
    seen["active_after"] = sorted(row_id for row_id, row in after.items() if row["state"] == "active")
    seen["smallest"] = sorted(smallest["rows"])
    page.get_by_role("button", name=ADVANCED).click()
    page.locator("#plugins .plugin-row:visible").first.wait_for()
    page.wait_for_timeout(1500)
    seen["switches_on_in_list"] = page.locator("#plugins .plugin-row .toggle-switch.on").count()
    page.get_by_role("button", name=ADVANCED).click()

    # And back to everything.
    card = _card(page, "Everything")
    card.get_by_role("button", name="Apply").click()
    seen["asks_everything"] = _words(card, None)
    card.get_by_role("button", name="Go").click()
    card.locator(".plugin-set-note:has-text('Done.')").wait_for()
    seen["everything_active"] = sorted(row["id"] for row in _status(context, base).values() if row["state"] == "active")
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["after_asked"] = {path: count for path, count in asked.items() if count > 12}
    seen["after_total"] = sum(asked.values())

    # The plugin that serves the sets turned off from the list: the plain list is the page, and nothing loops.
    context.request.post(f"{base}/api/plugins/thomas/plugin_sets/off")
    page.get_by_role("button", name=ADVANCED).wait_for(state="hidden", timeout=30_000)
    seen["off_cards"] = page.locator("#plugins .plugin-set-card:visible").count()
    seen["off_rows_shown"] = _rows_shown(page)
    seen["off_text"] = _words(page)
    asked.clear()
    page.wait_for_timeout(TEN_SECONDS)
    seen["off_asked_sets"] = asked[SETS]
    seen["off_asked_status"] = asked[STATUS]
    context.request.post(f"{base}/api/plugins/thomas/plugin_sets/on")
    page.locator("#plugins .plugin-set-card").first.wait_for(timeout=30_000)
    seen["back_cards"] = page.locator("#plugins .plugin-set-title").all_inner_texts()
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with (
        serving(tmp_path_factory.mktemp("sets-page"), script=OWN_CATALOG + _SERVE) as base,
        sync_playwright() as playwright,
    ):
        return _walk(base, playwright.chromium.launch(headless=True))


def test_the_default_view_is_three_cards_and_no_list_of_plugins(walked: dict[str, Any]) -> None:
    assert walked["cards"] == ["Everyday", "Just chat and build", "Everything"]
    assert walked["default_rows_shown"] == 0
    assert "Pick a ready-made set" in walked["default_text"]
    assert walked["advanced_button"] == 1
    assert walked["advanced_closed"] == "false"


def test_advanced_opens_every_plugin_under_the_headings_and_is_remembered_for_the_session_only(
    walked: dict[str, Any],
) -> None:
    assert walked["open_rows_shown"] == len(ALL)
    assert walked["rows_under_groups"] == len(ALL)
    assert walked["group_titles"] == [group["title"] for group in GROUPS]
    assert walked["required_lock"] == len(REQUIRED)
    assert walked["remembered_open"] is True
    assert walked["new_session_open"] is False
    assert walked["closed_again"] == 0


def test_a_set_asks_how_many_it_changes_before_it_does_anything(walked: dict[str, Any]) -> None:
    assert f"This turns on 0 plugins and turns off {walked['expect_off']}. Go?" in walked["asks"]
    assert walked["unchanged_while_asking"] == len(ALL) - 1  # every plugin but Idle awareness, which ships off
    assert "Go?" not in walked["cancelled_text"]


def test_applying_the_smallest_set_leaves_only_its_plugins_on_and_the_page_says_what_it_did(
    walked: dict[str, Any],
) -> None:
    assert walked["active_after"] == walked["smallest"]
    assert f"Done. Turned on 0, turned off {walked['expect_off']}." in walked["result"]
    assert "Left alone: " in walked["result"]
    assert "Chat and your saved sessions (It is part of how Thomas works" in walked["result"]
    assert "Build runs and upgrade loop (It is part of how Thomas works" in walked["result"]
    assert "You are using" not in walked["result"] and "Ready-made plugin sets (" not in walked["result"]
    assert walked["switches_on_in_list"] == len(walked["smallest"])


def test_everything_turns_every_plugin_back_on(walked: dict[str, Any]) -> None:
    assert re.search(r"This turns on \d+ plugins and turns off 0\. Go\?", walked["asks_everything"])
    assert walked["everything_active"] == sorted(ALL)


def test_the_pause_control_shows_what_is_true_and_presses_the_routes(walked: dict[str, Any]) -> None:
    assert walked["working_text"] == "Thomas is working Pause"
    assert walked["paused_text"] == "Thomas is paused (2 runs still finishing) Resume"
    assert walked["paused_buttons"] == ["Resume"]
    assert walked["pause_calls"] == ["POST /api/thomas/pause", "POST /api/thomas/resume"]


def test_with_no_pause_route_the_control_is_hidden_and_nothing_is_said(walked: dict[str, Any]) -> None:
    assert walked["no_pause_buttons"] == 0
    assert not re.search(r"Thomas is (working|paused)|Pause|Resume", walked["no_pause_text"])


def test_the_page_does_not_loop_in_ten_seconds(walked: dict[str, Any]) -> None:
    assert walked["quiet_asked"].get(PAUSE, 0) == 1, walked["quiet_asked"]  # a 404 is asked once and then left
    assert walked["quiet_asked"].get(SETS, 0) == 1, walked["quiet_asked"]
    assert walked["quiet_asked"].get(STATUS, 0) <= 4, walked["quiet_asked"]
    assert walked["quiet_total"] < 60, walked["quiet_total"]
    assert walked["pause_asked_in_ten_seconds"] <= 4
    assert walked["status_asked_in_ten_seconds"] <= 4
    assert walked["after_asked"] == {}, walked["after_asked"]
    assert walked["after_total"] < 60, walked["after_total"]
    assert walked["off_asked_sets"] == 0
    assert walked["off_asked_status"] <= 4


def test_with_the_sets_plugin_off_the_plain_list_is_the_page_and_turning_it_on_brings_the_cards_back(
    walked: dict[str, Any],
) -> None:
    assert walked["off_cards"] == 0
    assert walked["off_rows_shown"] == len(ALL)
    assert "pick a ready-made set" not in walked["off_text"].lower()
    assert walked["back_cards"] == ["Everyday", "Just chat and build", "Everything"]
