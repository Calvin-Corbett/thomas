"""The first time live talk needs Thomas's own ears, a window in the middle of the screen offers to set them up.

You described it: "when they try to use the voice the first time, they'll try it like normal, but instead it will pop up
a window and say you don't have voice set up, and the window will be like in the middle of the screen, and then they can
press set up later or set up now." Proves ``thomas/server/web/js/voice_mode.js`` in a real browser, with
``tests/web_fixtures/voice_page_fixture.py`` standing in for the voice routes (``needs_setup`` and its set-up steps).
"""

from __future__ import annotations

import pytest

from tests.test_the_talk_button_in_chat_and_in_code import LIVE_ON, SWITCH, listening, rest_on_the_microphone, spoken_by
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from tests.web_fixtures.voice_page_fixture import Voice, VoicePage, open_voice_page

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

WINDOW = "#tc-voice-setup"


def try_live_talk(page: VoicePage) -> None:
    """Turn live talk on the ordinary way: rest on the microphone, click the switch."""
    rest_on_the_microphone(page)
    page.page.click(SWITCH)
    page.page.wait_for_selector(LIVE_ON, timeout=5000)


def test_the_first_try_shows_a_window_in_the_middle_that_says_voice_is_not_set_up() -> None:
    with open_voice_page(Voice(needs_setup=True), recognition=True) as page:
        try_live_talk(page)
        page.page.wait_for_selector(WINDOW, timeout=5000)

        card = page.page.locator(f"{WINDOW} [role=dialog]")
        assert card.locator("h2").inner_text() == "You don’t have voice set up"
        assert card.locator("button").all_inner_texts() == ["Set up later", "Set up now"]
        assert "670 MB" in card.inner_text() and "CC-BY-4.0" in card.inner_text()
        box, view = card.bounding_box(), page.page.viewport_size
        assert box and view
        assert abs(box["x"] + box["width"] / 2 - view["width"] / 2) < 2
        assert abs(box["y"] + box["height"] / 2 - view["height"] / 2) < 2
        assert page.value("document.activeElement.textContent") == "Set up now"


def test_set_up_later_goes_on_with_the_browsers_hearing_and_does_not_ask_again_on_that_page() -> None:
    with open_voice_page(Voice(needs_setup=True, studio_running=False), recognition=True) as page:
        try_live_talk(page)
        page.page.click(f"{WINDOW} .tc-vs-later")
        assert page.page.locator(WINDOW).count() == 0
        spoken_by(page, "spoken")
        assert [row["message"] for row in page.value("window.__voice.chat")] == ["what the browser heard"]
        assert ("POST", "/api/voice/setup") not in page.voice.asked

        page.page.click(SWITCH)  # off, then on again: the choice was made, so no window this time
        page.page.wait_for_selector('#tc-voice-btn[aria-checked="false"]', timeout=5000)
        page.page.click(SWITCH)  # the slider is still open under the pointer
        page.page.wait_for_selector(LIVE_ON, timeout=5000)
        listening(page)
        assert page.page.locator(WINDOW).count() == 0


def test_set_up_now_shows_how_far_it_has_got_then_listens_with_thomas_s_own_ears() -> None:
    with open_voice_page(Voice(needs_setup=True)) as page:
        try_live_talk(page)
        page.page.click(f"{WINDOW} .tc-vs-now")
        page.page.wait_for_function(
            "() => (document.querySelector('#tc-voice-setup .tc-vs-status') || {}).textContent"
            "?.includes('Downloading 335 MB of 670 MB')",
            timeout=5000,
        )
        assert page.page.locator(f"{WINDOW} .tc-vs-later").inner_text() == "Hide"
        page.page.wait_for_selector(WINDOW, state="detached", timeout=10000)

        listening(page)
        assert page.voice.sockets, "live talk opened Thomas's own live line after setting up"
        assert page.value("window.ThomasVoiceLive.session().status.live.by") == "thomas"
        assert page.voice.setup_started == 1


def test_a_set_up_that_stops_says_why_and_can_be_tried_again() -> None:
    voice = Voice(needs_setup=True, setup_fails="the internet did not answer")
    with open_voice_page(voice, recognition=True) as page:
        try_live_talk(page)
        page.page.click(f"{WINDOW} .tc-vs-now")
        page.page.wait_for_function(
            "() => (document.querySelector('#tc-voice-setup .tc-vs-status') || {}).textContent"
            "?.startsWith('Setting up stopped: the internet did not answer')",
            timeout=10000,
        )
        again = page.page.locator(f"{WINDOW} .tc-vs-now")
        assert again.inner_text() == "Try again" and again.is_enabled()
        assert page.page.locator(f"{WINDOW} .tc-vs-later").inner_text() == "Set up later"


def test_escape_is_set_up_later() -> None:
    with open_voice_page(Voice(needs_setup=True, studio_running=False), recognition=True) as page:
        try_live_talk(page)
        page.page.wait_for_selector(WINDOW, timeout=5000)
        page.page.keyboard.press("Escape")
        assert page.page.locator(WINDOW).count() == 0
        spoken_by(page, "spoken")
        assert page.page.locator(LIVE_ON).count() == 1  # live talk stayed on, with the browser listening
