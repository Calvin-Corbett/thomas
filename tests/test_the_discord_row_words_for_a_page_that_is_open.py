"""What the Discord row says about the Channels page, read against a real window on a real server.

A reviewer found two sentences false: pressing Refresh on a page that was already open did not turn its Discord card to
Off, and an open page did not wait for a press, it asked once by itself and showed the 404 line while the card still
read On. Only a reload turns the card to Off. This walks a channel that was set up and is on, turns the row off under
an open page, and reads the card, the 404 line and the controls where a window shows them.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tomllib

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT
from tests.web_fixtures.thomas_chat_fixture import browser_ok

CARD = "[data-ui-id='channels.primary.discord']"
LINE = "404: Not Found"


def _words() -> dict[str, str]:
    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text(encoding="utf-8"))["row"]
    return next(row for row in rows if row["id"] == "discord")


def _post(page: Any, path: str, body: dict[str, Any] | None = None) -> int:
    script = (
        "async ([u, b]) => (await fetch(u, {method: 'POST', headers: {'content-type': 'application/json'},"
        " body: JSON.stringify(b || {})})).status"
    )
    return page.evaluate(script, [path, body])


def _open(page: Any, base: str) -> None:
    page.goto(f"{base}/classic?nav=channels", wait_until="domcontentloaded")
    page.wait_for_selector(CARD, timeout=90_000)
    page.evaluate(
        "() => ['easySetupModal', 'easySetupBackdrop'].forEach((id) => document.getElementById(id)?.remove())"
    )


def _read(page: Any, *, controls_too: bool = True) -> dict[str, Any]:
    card = " ".join(page.locator(CARD).inner_text().split())
    line = page.get_by_text(LINE, exact=True).locator("visible=true").count()
    controls = page.get_by_role("button", name="Open controls")
    if controls_too and controls.count():
        controls.first.click()
        page.wait_for_timeout(500)
    return {
        "card": card,
        "line": line,
        "off_button": page.get_by_role("button", name="Turn Channel Off").count(),
        "on_button": page.get_by_role("button", name="Turn Channel On").count(),
    }


def _walk(base: str, browser: Any) -> dict[str, Any]:
    context = browser.new_context(viewport={"width": 1500, "height": 950})
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(base, wait_until="domcontentloaded")
    assert (
        _post(page, "/api/channels/discord/config", {"bot_token": "a-test-token-1234", "owner_user_ids": ["1"]}) == 200
    )
    assert _post(page, "/api/channels/discord/enabled", {"enabled": True}) == 200
    _open(page, base)
    seen: dict[str, Any] = {"on": _read(page, controls_too=False)}
    assert _post(page, "/api/plugins/thomas/discord/off") == 200
    page.get_by_text(LINE, exact=True).first.wait_for(state="visible", timeout=90_000)
    seen["open_page_unpressed"] = _read(page, controls_too=False)
    page.get_by_role("button", name="Refresh").first.click()
    page.wait_for_timeout(3000)
    seen["open_page_refreshed"] = _read(page)
    _open(page, base)
    seen["reloaded"] = _read(page)
    context.close()
    return seen


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder: Path = tmp_path_factory.mktemp("discord-open-page")
    with serving(folder) as base, sync_playwright() as playwright:
        return _walk(base, playwright.chromium.launch(headless=True))


def test_an_open_page_shows_the_404_line_by_itself_while_its_card_keeps_reading_on(seen: dict[str, Any]) -> None:
    page = seen["open_page_unpressed"]
    assert "On channel" in page["card"] and page["line"] == 1, seen


def test_pressing_refresh_on_an_open_page_does_not_turn_its_card_to_off(seen: dict[str, Any]) -> None:
    page = seen["open_page_refreshed"]
    assert "On channel" in page["card"] and page["line"] == 1 and page["off_button"] == 1, seen


def test_only_a_reload_turns_the_card_to_off_and_the_button_to_turn_on(seen: dict[str, Any]) -> None:
    page = seen["reloaded"]
    assert "Off channel" in page["card"] and page["on_button"] == 1 and page["off_button"] == 0, seen


def test_the_words_say_what_those_three_windows_show() -> None:
    said = " ".join(_words()["off_means"].split())
    assert "reload" in said and "keeps reading On" in said and "Turn Channel On" in said, said
    assert "press Refresh, its Discord card reads Off" not in said
    assert "keeps showing what it last saw until you press Refresh" not in said
    assert "Not configured" not in said
