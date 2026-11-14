"""Talking to Thomas by voice, off: six routes answer 404, a server started that way never loads them, the file stays.

``thomas.server.rows.voice`` serves the six routes under ``/api/voice``. They only keep a few saved choices and call
Voice Studio, which is a separate program, so off takes away those calls and nothing else. These tests hold the row's
words to that. The route module is ``thomas.server.routes.voice_routes``, and it hands its work to
``thomas.server.voice_studio``, ``thomas.server.voice_settings`` and ``thomas.server.voice_fast_model``. The routes'
behaviour, with a stand-in for Voice Studio, is in ``tests/test_the_voice_routes_talk_to_voice_studio.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, module_of, named
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.server import app_core
from thomas.server.proof.selection import select

ROW = "voice"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/voice/status": "GET /api/voice/status",
    "PUT /api/voice/settings": "PUT /api/voice/settings",
    "GET /api/voice/voices": "GET /api/voice/voices",
    "POST /api/voice/speak": "POST /api/voice/speak",
    "POST /api/voice/transcribe": "POST /api/voice/transcribe",
    "GET /api/voice/live": "GET /api/voice/live",
    "GET /api/voice/setup": "GET /api/voice/setup",
    "POST /api/voice/setup": "POST /api/voice/setup",
}
OWN_CODE = ("thomas.server.rows.voice", "thomas.server.routes.voice_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/voice/status", "HEAD /api/voice/voices", "HEAD /api/voice/live", "HEAD /api/voice/setup"}


HERE = Path(__file__)
ROUTE_TESTS = ROOT / "tests" / "test_the_voice_routes_talk_to_voice_studio.py"
BUTTON_TESTS = ROOT / "tests" / "test_the_talk_button_in_chat_and_in_code.py"
OFF_TESTS = ROOT / "tests" / "test_the_talk_button_with_the_plugin_off.py"
EARS_TESTS = ROOT / "tests" / "test_thomas_hears_you_live_on_this_computer.py"
SETUP_TESTS = ROOT / "tests" / "test_thomas_sets_up_his_own_ears.py"
WINDOW_TESTS = ROOT / "tests" / "test_the_voice_setup_window.py"
OFF = "test_with_the_row_off_every_route_answers_404_and_none_is_listed"
SAVED = "test_a_saved_voice_lands_in_the_data_folder_and_survives_off_and_on"
STOP = "test_stop_now_cuts_off_a_piece_of_speech_still_being_made"
SWITCH = "test_resting_on_the_microphone_turns_it_into_a_switch_in_both_modes"
IN_CHAT = "test_live_talk_in_chat_sends_each_pause_with_the_small_model_and_talks_while_the_reply_is_written"
IN_CODE = "test_live_talk_in_code_sends_with_the_small_model_and_reads_the_reply_aloud"
LIVE_LINE = "test_the_live_line_passes_the_microphone_to_voice_studio_and_its_words_back"
WORDS = {
    "Lets you talk with Thomas out loud in Chat and in Code.": (IN_CHAT, IN_CODE),
    "Rest the pointer on the microphone under the message box for a moment and it turns into a switch, and clicking "
    "the switch turns the microphone into a speaker and live talk on.": (
        SWITCH,
        IN_CHAT,
        "test_turning_it_off_stops_listening_and_talking",
    ),
    "Speak, and when you pause what you said is sent like any message to the smallest and fastest model you have set "
    "up, or to the model you chose when none is small.": (
        IN_CHAT,
        IN_CODE,
        "test_the_next_pause_is_the_next_message_without_touching_anything",
        "test_with_no_small_model_set_up_the_turn_keeps_the_model_you_chose",
        "test_the_smallest_ready_model_is_picked_by_its_size_word",
        "test_a_model_that_makes_pictures_is_never_the_one_that_answers_your_voice",
    ),
    "Thomas reads his answer aloud a sentence at a time while he is still writing it, and he stops when you start "
    "talking.": (IN_CHAT, "test_talking_while_thomas_speaks_stops_him_and_sends_what_you_said"),
    "Thomas listens by himself, on this computer, with NVIDIA's Parakeet TDT 0.6B v3 speech model, shared under the "
    "CC BY 4.0 licence and run with sherpa-onnx, so no other program has to be open and nothing has to be accepted.": (
        "test_status_says_thomas_listens_himself_with_credit_even_when_voice_studio_is_closed",
        "test_the_live_line_hears_through_thomas_with_no_voice_studio",
        "test_the_real_model_writes_down_a_real_recording_cut_at_its_pause",
    ),
    "The first time you turn live talk on before that model is on your computer, a window in the middle of the screen "
    "says you don't have voice set up and offers Set up later or Set up now.": (
        "test_the_first_try_shows_a_window_in_the_middle_that_says_voice_is_not_set_up",
        "test_status_says_what_setting_up_would_download_until_thomas_can_listen",
    ),
    "Set up now downloads the model once from its makers, about 670 MB, checks every file, installs the speech engine "
    "first when it is missing and shows how far it has got, and live talk then listens with it.": (
        "test_set_up_now_shows_how_far_it_has_got_then_listens_with_thomas_s_own_ears",
        "test_setting_up_downloads_each_file_from_its_makers_checks_it_and_puts_it_in_place",
        "test_every_listed_model_says_where_it_comes_from_its_licence_and_how_to_check_each_file",
        "test_a_missing_speech_engine_is_installed_first_and_a_failed_install_says_why",
        "test_the_engine_install_is_the_pinned_sherpa_onnx_into_thomas_s_own_python_with_no_window",
        "test_set_up_now_starts_the_named_model_into_the_data_folder_and_refuses_one_not_named_or_listed",
    ),
    "A set-up that stops says why and can be tried again.": (
        "test_a_set_up_that_stops_says_why_and_can_be_tried_again",
        "test_a_file_that_does_not_match_its_checksum_is_thrown_away_and_the_set_up_says_so",
    ),
    "Until it is set up, or after Set up later, he listens with Voice Studio when it can, or with your browser's own "
    "hearing.": (
        LIVE_LINE,
        "test_set_up_later_goes_on_with_the_browsers_hearing_and_does_not_ask_again_on_that_page",
        "test_when_voice_studio_has_no_live_model_the_browsers_hearing_is_the_backup",
        "test_status_says_why_live_listening_is_not_ready",
    ),
    "He speaks with Voice Studio's voice when that program is running, and with your browser's own voice when it is "
    "not.": (IN_CHAT, "test_without_voice_studio_the_browsers_own_hearing_and_voice_are_used"),
    "This never starts Voice Studio.": ("test_nothing_in_the_voice_code_starts_a_program",),
    "A quick click on the microphone still types what you say, as before.": (
        "test_a_quick_click_on_the_microphone_still_types_what_you_say",
    ),
    "You can change the voice at any time, and one voice is saved as your default.": (
        "test_the_voice_can_be_changed_at_any_time_and_the_default_is_one_choice",
        "test_the_voice_you_choose_is_named_under_the_message_box_and_is_the_one_that_speaks",
        "test_one_default_voice_is_saved_and_a_change_replaces_it",
    ),
    "While this is off, the microphone under the message box never turns into a switch, and it still types what you "
    "say into the message box, as before.": (
        "test_with_the_plugin_off_there_is_no_button_and_the_microphone_is_unchanged",
        "test_the_microphone_beside_it_still_types_what_you_say_with_the_plugin_off",
    ),
    "A page you already have open keeps the switch until you reload it, and turning it on then says voice is turned "
    "off instead of listening.": ("test_a_page_open_when_the_plugin_is_turned_off_says_so_and_does_not_ask_again",),
    "Nothing keeps asking Thomas while it is off.": ("test_with_the_plugin_off_the_page_asks_once_and_never_again",),
    "Other programs that ask for the voice choices, live listening, setting up Thomas's hearing, a recording turned "
    "into words or words turned into sound get 404: Not Found.": (OFF,),
    "The voice you chose stays saved and is there again when this is back on.": (SAVED,),
    "A recording or a piece of speech that is being made at that moment is cut off, and the program that asked has "
    "to ask again.": (STOP,),
}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("voice-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("voice-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_the_row_names_its_route_module() -> None:
    """A press on imports what a row names in a thread, and the proof of every row watches only what it names."""
    entry = next(row for row in ROWS if row.id == ROW)
    assert sorted(named(entry)) == sorted(set(OWN_CODE) - {module_of(entry)})


def test_turning_it_on_brings_back_all_eight_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    # What each answers to an empty body on the real store, whether or not Voice Studio is running on this machine.
    assert seen["on"] == {
        "GET /api/voice/status": 200,
        "PUT /api/voice/settings": 200,  # nothing to change
        "GET /api/voice/voices": 200,  # an empty list when Voice Studio is not running
        "POST /api/voice/speak": 400,  # no text
        "POST /api/voice/transcribe": 400,  # not a recording
        "GET /api/voice/live": 400,  # a websocket only
        "GET /api/voice/setup": 200,  # what setting up would download
        "POST /api/voice/setup": 400,  # no model named, so nothing starts downloading
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_saved_voice_lands_in_the_data_folder_and_survives_off_and_on(tmp_path: Path, own_data_dir: Path) -> None:
    """The words say the voice you chose stays saved. This saves one through the live table and reads the file."""

    async def scenario() -> tuple[int, str, str]:
        app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            saved = await client.put("/api/voice/settings", json={"voice": "nova", "engine": "browser"})
            await client.post("/api/plugins/thomas/voice/off")
            await client.post("/api/plugins/thomas/voice/on")
            again = await (await client.get("/api/voice/status")).json()
            return saved.status, again["settings"]["voice"], again["settings"]["engine"]

    status, voice, engine = asyncio.run(scenario())
    store = tmp_path / "memory" / ".thomas" / "voice.json"

    assert (status, voice, engine) == (200, "nova", "browser")
    assert json.loads(store.read_text(encoding="utf-8"))["voice"] == "nova"


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/voice.py",
        "thomas/server/routes/voice_routes.py",
        "thomas/server/voice_studio.py",
        "thomas/server/voice_settings.py",
        "thomas/server/voice_fast_model.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_voice_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_voice_routes_talk_to_voice_studio.py" in chosen


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    assert sentences(ROW, "about", "off_means", "stop_now") == list(WORDS)
    assert unnamed_tests(WORDS, HERE, ROUTE_TESTS, BUTTON_TESTS, OFF_TESTS, EARS_TESTS, SETUP_TESTS, WINDOW_TESTS) == []
