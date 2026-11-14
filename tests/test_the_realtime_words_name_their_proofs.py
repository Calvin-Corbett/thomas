"""Every sentence the Plugins page says about the realtime row, each with the tests that show it.

The words live in ``thomas/server/rows/default.toml``, and that name here is what makes a check run this file when they
change. It reads text and starts nothing, so a landing pays almost nothing for it. A sentence added, changed or dropped
fails here until this list has it with a test that shows it, so none of them lands on the strength of having been true
once. Reading the page is what ``tests/test_the_realtime_page_through_off_and_on.py`` does.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re

import pytest

from tests.row_proof_fixture import ROOT, ROWS
from thomas.server.proof.selection import select

THE_ROUTES = "tests/test_turning_realtime_off_touches_only_its_routes.py"
THE_SESSION = "tests/test_the_realtime_socket_through_off_and_on.py"
THE_PAGE = "tests/test_the_realtime_page_through_off_and_on.py"
WORDS = {
    "about": {
        "A page of its own, headed Realtime Human Assistant Layer, that was meant for talking to Thomas by voice or by "
        "typing.": (("test_the_page_is_headed_the_way_the_words_say", THE_PAGE),),
        "Nothing in Thomas links to it or uses it, so you reach it only by typing its address.": (
            ("test_no_page_opens_this_one_and_nothing_reads_where_it_is_advertised", THE_ROUTES),
        ),
        "As it comes, pressing Connect there shows a warning that it is disabled, and the page keeps trying again about "
        "twice a second until you press Connect a second time.": (
            ("test_as_shipped_connect_shows_a_warning_and_keeps_trying_about_twice_a_second", THE_PAGE),
            ("test_pressing_connect_a_second_time_stops_it_and_leaves_the_warning", THE_PAGE),
            ("test_as_shipped_the_socket_says_it_is_disabled_and_an_upload_is_refused", THE_SESSION),
        ),
        "If you change the setting that warning names, it connects, but anything you send comes back as an error.": (
            ("test_with_its_setting_changed_every_message_comes_back_as_an_error", THE_SESSION),
        ),
        "In Docker, or installed with pip somewhere outside the Thomas folder, this page is left out, so its address "
        "shows 404: Not Found even with this on.": (
            ("test_with_the_page_left_out_of_an_install_only_the_page_goes", THE_SESSION),
            ("test_a_pip_copy_finds_the_page_only_inside_the_thomas_folder", THE_SESSION),
        ),
    },
    "off_means": {
        "While this is off, nothing you normally use changes, because nothing in Thomas uses this page.": (
            ("test_no_page_opens_this_one_and_nothing_reads_where_it_is_advertised", THE_ROUTES),
        ),
        "Typing its address shows 404: Not Found, and so does reloading it.": (
            ("test_typing_its_address_or_reloading_it_with_the_row_off_shows_a_bare_404", THE_PAGE),
        ),
        "If you pressed Connect on a copy that is still open, it stays on screen and says there was a WebSocket error and "
        "that text mode still works, but it does not: what you type appears there and nothing answers.": (
            ("test_a_page_still_open_says_text_works_and_nothing_answers_it", THE_PAGE),
        ),
        "It tries again about every eight seconds for as long as it stays open, and once this is back on it shows the "
        "disabled warning again and goes back to trying about twice a second.": (
            ("test_a_page_still_open_settles_to_one_try_about_every_eight_seconds_and_does_not_loop", THE_PAGE),
            ("test_a_page_still_open_goes_back_to_trying_about_twice_a_second_once_the_row_is_back_on", THE_PAGE),
        ),
        "Files already dropped onto it stay where they were saved.": (
            ("test_a_file_already_dropped_on_it_stays_through_off_and_on", THE_SESSION),
        ),
    },
    "stop_now": {
        "Only a file still being dropped onto that page can hold this up.": (
            ("test_an_open_socket_does_not_hold_the_off_switch_and_what_it_began_ends_with_it", THE_SESSION),
            ("test_stop_now_cuts_off_a_file_on_its_way_in_and_keeps_none_of_it", THE_SESSION),
        ),
        "It is cut off, none of it is kept, and it needs sending again.": (
            ("test_stop_now_cuts_off_a_file_on_its_way_in_and_keeps_none_of_it", THE_SESSION),
        ),
    },
}


@pytest.mark.parametrize("word", list(WORDS))
def test_every_sentence_of_the_words_names_the_test_that_shows_it(word: str) -> None:
    written = next(row for row in ROWS if row.id == "realtime").config["words"][word]

    assert re.split(r"(?<=\.)\s+", written) == list(WORDS[word])
    shown_by = {proof for proofs in WORDS[word].values() for proof in proofs}
    missing = [name for name, file in shown_by if f"def {name}(" not in (ROOT / file).read_text(encoding="utf-8")]
    assert missing == []


def test_a_change_to_the_list_runs_this_file() -> None:
    assert (
        "tests/test_the_realtime_words_name_their_proofs.py" in select(ROOT, ["thomas/server/rows/default.toml"]).files
    )
