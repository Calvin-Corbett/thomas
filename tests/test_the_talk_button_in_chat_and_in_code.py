"""Live talk, in Chat and in Code, in a real browser with the plugin on.

Proves ``thomas.server.rows.voice`` through the page that uses it: ``thomas/server/web/js/voice_mode.js`` (the microphone
that becomes a switch), ``voice_live.js`` (listening, sending and talking back) and ``voice_speech.js``, loaded by
``thomas/server/web/chat.html``. The microphone is the browser's own fake one (``--use-fake-device-for-media-stream``), so
real sound goes over the live websocket. ``tests/web_fixtures/voice_page_fixture.py`` stands in for the voice routes and
for Voice Studio's live listening, and replaces the two things a headless browser cannot do, the browser's voice and
playing a sound, with recorders that the tests read back.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import pytest

from tests.web_fixtures.thomas_chat_fixture import browser_ok
from tests.web_fixtures.voice_page_fixture import Voice, VoicePage, answer_code_runs, open_voice_page

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

MODES = ["chat", "code"]
SWITCH = "#tc-voice-btn"
LIVE_ON = '#tc-voice-btn[aria-checked="true"]'


def rest_on_the_microphone(page: VoicePage) -> None:
    """Rest the pointer on the microphone until it has become the slider."""
    page.page.hover("#tc-mic-btn")
    page.page.wait_for_selector('#tc-voice-dock[data-open="true"]', timeout=5000)


def turn_on(page: VoicePage, *, mode: str = "chat") -> None:
    if mode == "code":
        answer_code_runs(page.page)
    rest_on_the_microphone(page)
    page.page.click(SWITCH)
    page.page.wait_for_selector(LIVE_ON, timeout=5000)


def listening(page: VoicePage) -> None:
    """Wait until the microphone is open and its sound is going to the live line."""
    page.page.wait_for_function(
        "() => { const s = window.ThomasVoiceLive.session(); return !!(s && s.ears); }", timeout=10000
    )


def spoken_by(page: VoicePage, how: str, at_least: int = 1) -> None:
    """Wait for the reply to be said (a played sound for Voice Studio, an utterance for the browser) and for listening."""
    page.page.wait_for_function(f"() => window.__voice.{how}.length >= {at_least}", timeout=30000)
    page.page.wait_for_selector('#tc-voice-btn[data-voice-state="listening"]', timeout=30000)


def selected_model(page: VoicePage) -> str:
    return page.value("window.ThomasModelSelection.current().modelId")


@pytest.mark.parametrize("mode", MODES)
def test_resting_on_the_microphone_turns_it_into_a_switch_in_both_modes(mode: str) -> None:
    with open_voice_page(mode=mode) as page:
        assert page.value("window.ThomasUnifiedModes.mode()") == mode
        assert page.page.locator("#tc-voice-more").count() == 0  # one control now, not three
        assert page.value("getComputedStyle(document.getElementById('tc-voice-btn')).opacity") == "0"
        page.page.hover("#tc-mic-btn")
        page.page.wait_for_timeout(500)
        assert page.value("document.getElementById('tc-voice-dock').dataset.open") == "false"  # not after a moment
        page.page.wait_for_selector('#tc-voice-dock[data-open="true"]', timeout=5000)
        assert page.value("document.getElementById('tc-voice-btn').getAttribute('role')") == "switch"
        assert page.value("document.getElementById('tc-voice-btn').getAttribute('aria-checked')") == "false"
        page.page.mouse.move(5, 5)  # leaving it alone folds it back
        page.page.wait_for_selector('#tc-voice-dock[data-open="false"]', timeout=5000)
        assert page.page.locator("#tc-mic-btn").is_visible()
        assert not page.errors, page.errors


def test_a_quick_click_on_the_microphone_still_types_what_you_say() -> None:
    with open_voice_page(recognition=True) as page:
        page.page.click("#tc-mic-btn")
        page.page.wait_for_timeout(400)
        page.page.click("#tc-mic-btn")
        page.page.wait_for_function(
            "() => document.getElementById('tc-input').value.includes('what the browser heard')"
        )
        assert page.value("document.getElementById('tc-voice-dock').dataset.open") == "false"
        assert page.value("window.__voice.chat.length") == 0  # typed in, not sent


def test_live_talk_in_chat_sends_each_pause_with_the_small_model_and_talks_while_the_reply_is_written() -> None:
    with open_voice_page() as page:
        turn_on(page)
        spoken_by(page, "played", at_least=3)
        sent = page.value("window.__voice.chat")
        assert [row["message"] for row in sent] == ["what time is it"]
        assert sent[0]["model_id"] == "fixture-mini"  # the small model the server named
        assert page.voice.frames >= 5  # real microphone sound reached the live line
        assert page.voice.said[0]["text"].startswith("piece 0 of the reply")
        assert len(page.voice.said) > 1  # a sentence at a time, not one block at the end
        assert page.value("window.__voice.speakWhileWriting[0]") is True  # talking began before the reply was finished
        assert page.value("window.__voice.spoken") == []  # Voice Studio spoke, not the browser
        assert selected_model(page) == "fixture-1"  # your own choice is back the moment the message is on its way
        assert page.page.locator(LIVE_ON).count() == 1  # still on, listening for the next thing you say
        assert not page.errors, page.errors


def test_the_next_pause_is_the_next_message_without_touching_anything() -> None:
    voice = Voice(utterances=["what time is it", "and tomorrow"])
    with open_voice_page(voice) as page:
        turn_on(page)
        page.page.wait_for_function("() => window.__voice.chat.length >= 2", timeout=30000)
        assert [row["message"] for row in page.value("window.__voice.chat")] == ["what time is it", "and tomorrow"]


def test_live_talk_in_code_sends_with_the_small_model_and_reads_the_reply_aloud() -> None:
    with open_voice_page(mode="code") as page:
        turn_on(page, mode="code")
        spoken_by(page, "played")
        sent = page.value("window.__voice.code")
        assert [row["message"] for row in sent] == ["what time is it"]
        assert sent[0]["model_id"] == "fixture-mini"
        assert page.voice.said[0]["text"] == "Here is the answer from Code."
        assert selected_model(page) == "fixture-1"
        assert any(path.startswith("/api/voice/status?fresh=1&surface=code") for _, path in page.voice.asked)
        assert not page.errors, page.errors


def test_with_no_small_model_set_up_the_turn_keeps_the_model_you_chose() -> None:
    with open_voice_page(Voice(fast_model=None)) as page:
        turn_on(page)
        spoken_by(page, "played")
        assert page.value("window.__voice.chat")[0]["model_id"] == "fixture-1"


@pytest.mark.parametrize("mode", MODES)
def test_without_voice_studio_the_browsers_own_hearing_and_voice_are_used(mode: str) -> None:
    with open_voice_page(Voice(studio_running=False), mode=mode, recognition=True) as page:
        turn_on(page, mode=mode)
        spoken_by(page, "spoken")
        sent = page.value("window.__voice.chat" if mode == "chat" else "window.__voice.code")
        assert [row["message"] for row in sent] == ["what the browser heard"]
        assert page.voice.frames == 0 and page.voice.sockets == []  # nothing was sent to Voice Studio
        assert page.value("window.__voice.played") == []
        assert page.value("window.__voice.spoken")[0]["text"].startswith("piece 0" if mode == "chat" else "Here is")


def test_when_voice_studio_has_no_live_model_the_browsers_hearing_is_the_backup() -> None:
    with open_voice_page(Voice(live_model=None, live_why="Licence not accepted"), recognition=True) as page:
        turn_on(page)
        spoken_by(page, "played")  # Voice Studio still speaks
        assert [row["message"] for row in page.value("window.__voice.chat")] == ["what the browser heard"]


def test_with_no_way_to_listen_it_says_why_and_the_switch_goes_back() -> None:
    with open_voice_page(Voice(live_model=None, live_why="Licence not accepted for parakeet"), no_ears=True) as page:
        rest_on_the_microphone(page)
        page.page.click(SWITCH)
        page.page.wait_for_selector('#tc-voice-btn[aria-checked="false"]', timeout=10000)
        page.page.wait_for_function("() => document.getElementById('tc-voice-panel').textContent.includes('Licence')")
        assert "Licence not accepted for parakeet" in page.page.inner_text("#tc-voice-panel")
        assert page.value("window.__voice.chat.length") == 0


def test_talking_while_thomas_speaks_stops_him_and_sends_what_you_said() -> None:
    voice = Voice()
    with open_voice_page(voice) as page:
        page.page.evaluate("() => { window.__voice.hold = true; }")  # a sound that never ends by itself
        turn_on(page)
        page.page.wait_for_selector('#tc-voice-btn[data-voice-state="speaking"]', timeout=30000)
        listening(page)
        voice.hear("wait a", final=False)
        page.page.wait_for_function("() => window.__voice.paused >= 1", timeout=5000)  # the sound playing was stopped
        voice.hear("wait a second")
        page.page.wait_for_function("() => window.__voice.chat.length >= 2", timeout=10000)
        assert page.value("window.__voice.chat[1].message") == "wait a second"


def test_turning_it_off_stops_listening_and_talking() -> None:
    voice = Voice(utterances=[])
    with open_voice_page(voice) as page:
        turn_on(page)
        page.page.wait_for_timeout(800)
        frames = voice.frames
        assert frames > 0
        page.page.click(SWITCH)
        page.page.wait_for_selector('#tc-voice-btn[aria-checked="false"]', timeout=5000)
        page.page.wait_for_timeout(800)
        after = voice.frames
        page.page.wait_for_timeout(800)
        assert voice.frames == after  # nothing more is sent once it is off
        assert page.value("window.ThomasVoiceLive.running()") is False


def test_the_voice_can_be_changed_at_any_time_and_the_default_is_one_choice() -> None:
    with open_voice_page(Voice(studio_running=True)) as page:
        rest_on_the_microphone(page)
        page.page.click(SWITCH, button="right")
        page.page.wait_for_selector("#tc-voice-panel select option", state="attached", timeout=5000)
        labels = page.page.locator("#tc-voice-pick option").all_inner_texts()
        assert labels == [
            "Default voice",
            "Voice Studio: Alloy",
            "Voice Studio: Mine",
            "This browser: Test Voice A",
            "This browser: Test Voice B",
        ]
        page.page.select_option("#tc-voice-pick", "voicestudio|p1")
        page.page.wait_for_timeout(300)
        page.page.select_option("#tc-voice-pick", "auto|default")
        page.page.wait_for_timeout(300)
        assert page.voice.saved == [{"engine": "voicestudio", "voice": "p1"}, {"engine": "auto", "voice": "default"}]


def test_the_voice_you_choose_is_named_under_the_message_box_and_is_the_one_that_speaks() -> None:
    voice = Voice(utterances=[])
    with open_voice_page(voice) as page:
        rest_on_the_microphone(page)
        page.page.click(SWITCH, button="right")
        page.page.wait_for_selector("#tc-voice-pick option", state="attached", timeout=5000)
        page.page.select_option("#tc-voice-pick", "voicestudio|p1")
        page.page.wait_for_timeout(300)
        page.page.keyboard.press("Escape")
        page.page.click(SWITCH)
        page.page.wait_for_selector(LIVE_ON, timeout=5000)
        page.page.wait_for_function("() => document.getElementById('tc-voice-line').textContent.includes('Mine')")
        listening(page)
        voice.hear("hello there")
        spoken_by(page, "played")
        assert page.voice.said[0]["voice"] == "p1"
