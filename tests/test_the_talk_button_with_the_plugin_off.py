"""Live talk with the plugin off, and a page that was open when it was turned off, in a real browser.

Proves that ``thomas.server.rows.voice`` turned off leaves ``thomas/server/web/js/voice_mode.js`` with nothing to draw
and nothing to ask: the page asks ``/api/voice/status`` once, gets 404 and stops, in Chat and in Code, and a page that was
already open says voice is turned off when its switch is clicked and then asks no more. The stand-in routes are in
``tests/web_fixtures/voice_page_fixture.py``. A server really started with the plugin off answers 404 on every route, which
``tests/test_turning_voice_off_touches_only_its_routes.py`` shows.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import pytest

from tests.web_fixtures.thomas_chat_fixture import browser_ok
from tests.web_fixtures.voice_page_fixture import Voice, open_voice_page

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

MODES = ["chat", "code"]
TEN_SECONDS = 10000


@pytest.mark.parametrize("mode", MODES)
def test_with_the_plugin_off_there_is_no_button_and_the_microphone_is_unchanged(mode: str) -> None:
    with open_voice_page(Voice(row_on=False), mode=mode) as page:
        assert page.value("window.ThomasUnifiedModes.mode()") == mode
        assert page.page.locator("#tc-voice-btn").count() == 0
        assert page.page.locator("#tc-voice-more").count() == 0
        assert page.page.locator("#tc-voice-panel").count() == 0
        assert page.page.locator("#tc-mic-btn").is_visible()
        assert not page.errors, page.errors


@pytest.mark.parametrize("mode", MODES)
def test_with_the_plugin_off_the_page_asks_once_and_never_again(mode: str) -> None:
    with open_voice_page(Voice(row_on=False), mode=mode) as page:
        page.page.wait_for_timeout(TEN_SECONDS)
        assert page.asked() == [("GET", "/api/voice/status")]


@pytest.mark.parametrize("mode", MODES)
def test_with_the_plugin_on_and_nobody_pressing_nothing_is_asked_again(mode: str) -> None:
    with open_voice_page(mode=mode) as page:
        page.page.wait_for_timeout(TEN_SECONDS)
        assert page.asked() == [("GET", "/api/voice/status")]


@pytest.mark.parametrize("mode", MODES)
def test_the_microphone_beside_it_still_types_what_you_say_with_the_plugin_off(mode: str) -> None:
    with open_voice_page(Voice(row_on=False), mode=mode, recognition=True) as page:
        page.page.click("#tc-mic-btn")
        page.page.wait_for_timeout(300)
        page.page.click("#tc-mic-btn")
        page.page.wait_for_function(
            "() => document.getElementById('tc-input').value.includes('what the browser heard')"
        )
        assert page.value("window.__voice.chat.length + window.__voice.code.length") == 0  # typed in, not sent


@pytest.mark.parametrize("mode", MODES)
def test_a_page_open_when_the_plugin_is_turned_off_says_so_and_does_not_ask_again(mode: str) -> None:
    voice = Voice()
    with open_voice_page(voice, mode=mode) as page:
        voice.row_on = False  # turned off while this page stays open
        page.page.hover("#tc-mic-btn")
        page.page.wait_for_selector('#tc-voice-dock[data-open="true"]', timeout=5000)
        page.page.click("#tc-voice-btn")
        page.page.wait_for_function(
            "() => document.getElementById('tc-voice-panel').textContent.includes('turned off')"
        )
        assert "Voice is turned off" in page.page.inner_text("#tc-voice-panel")
        assert page.page.locator("#tc-voice-btn").is_hidden()
        assert page.value("window.__voice.chat.length + window.__voice.code.length") == 0
        before = len(page.asked())
        page.page.wait_for_timeout(TEN_SECONDS)
        assert len(page.asked()) == before
        assert page.page.locator("#tc-mic-btn").is_visible()
        assert not page.errors, page.errors
