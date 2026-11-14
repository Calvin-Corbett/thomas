"""A search result is written by a stranger, and the results page treats it so.

Every field on the results page -- the headline, the description, the link --
is chosen by whoever ranks for the query. Two things can go wrong, and neither
one shows up as a broken-looking page:

* text that breaks out of the markup it sits in, and
* a link whose *scheme* is not the web. Escaping an href is no defence here:
  ``javascript:alert(1)`` survives escaping completely intact, and the
  DuckDuckGo redirect unwrapper will happily hand one back because the
  wrapper's target is attacker-chosen. That link would land in the chrome
  document -- the one document holding the desktop bridge.

Driven through ``tests/web_node/browser_search_rows.mjs``, which runs the real
module in a vm context, so these assert on what the module actually produces
rather than on the shape of its source.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "browser_shell_search.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "browser_search_rows.mjs"

pytestmark = pytest.mark.skipif(not SEARCH_JS.exists(), reason="browser shell is not present in this checkout")


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    result = subprocess.run(
        ["node", str(HARNESS), str(SEARCH_JS)],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this Windows decodes the report as cp1252
        # and the breadcrumb separator arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ── the address grammar ──────────────────────────────────────────────────


def test_a_question_opens_our_own_page_and_an_address_stays_an_address(report) -> None:
    assert report["search_url"] == "thomas://search?q=electron%20webcontentsview"
    assert report["bare_host"] == "https://example.com"
    assert report["full_url"] == "https://example.com/a?b=c"
    assert report["uppercase_url"] == "HTTPS://example.com/a"
    assert report["is_search"] is True
    assert report["is_search_for_site"] is False


def test_a_query_survives_the_round_trip_through_its_address(report) -> None:
    # & # " and % are exactly the characters a naive concatenation loses, and
    # losing them means searching for something the person did not type.
    assert report["round_trip"] == 'a & b #c "d" 100%'


# ── schemes ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    ["scheme_javascript", "scheme_data", "scheme_file", "scheme_vbscript", "scheme_mixed_case"],
)
def test_a_link_that_is_not_the_web_is_refused(report, key: str) -> None:
    assert report[key] == "", f"{key} produced a usable href"


def test_an_ordinary_result_link_is_left_alone(report) -> None:
    assert report["scheme_http"] == "http://example.com/a"
    assert report["scheme_https"] == "https://example.com/a"
    assert report["scheme_garbage"] == ""


# ── rendering ────────────────────────────────────────────────────────────


def test_a_hostile_title_renders_as_text_not_as_markup(report) -> None:
    row = report["row_hostile_title"]
    assert "<script>" not in row
    assert "window.pwned" in row, "the text should still be shown, just inertly"
    assert "&lt;script&gt;" in row


def test_a_hostile_snippet_cannot_open_an_attribute(report) -> None:
    row = report["row_hostile_snippet"]
    # The words "onmouseover=" survive as *text*, and should -- that is what
    # the result said. What must not survive is the quote that would end the
    # attribute it sits in and start a live handler.
    assert 'onmouseover="' not in row
    assert "&quot; onmouseover=&quot;" in row


def test_a_host_with_encoded_markup_cannot_break_out_of_the_avatar(report) -> None:
    row = report["row_hostile_host"]
    assert 'onmouseover="' not in row
    assert 'href="https://example.com%22%20onmouseover%3Dalert(1).test/a"' in row


def test_an_ordinary_result_still_reads_like_a_result(report) -> None:
    # The escaping must not be so eager that a normal row stops being useful.
    row = report["row_plain"]
    assert "WebContentsView | Electron" in row
    assert 'href="https://www.electronjs.org/docs/latest/api/web-contents-view"' in row
    assert "A View that displays a WebContents." in row
    assert "electronjs.org" in row


def test_a_result_with_no_description_omits_the_snippet_rather_than_showing_an_empty_line(
    report,
) -> None:
    assert "bt-sr-snip" not in report["row_no_snippet"]
    assert "Bare" in report["row_no_snippet"]


# ── the way back ─────────────────────────────────────────────────────────


def test_a_result_opened_from_search_owes_its_way_back_to_the_results(report) -> None:
    # The tab was created for this result, so its own history holds nothing:
    # delegating the step there is what leaves Back lit and inert.
    assert report["back_frame_from_search"] == "search"
    assert report["back_view_did_not_move"] == "search"


def test_a_framed_page_is_never_asked_for_a_step_this_page_cannot_take(report) -> None:
    # A frame showing another origin will not let this document touch its
    # history -- the property access itself throws -- so a step handed to the
    # frame is a button that lights up and does nothing. That is the whole
    # failure, and it was the state of a tab opened from the + page or a
    # bookmark, where nothing had been recorded yet. With no record there is
    # nowhere to go, and the bar says so rather than pretending.
    assert report["back_frame_plain"] == "none"
    assert report["fwd_web_plain"] == "none"
    assert report["fwd_web_ahead_spent"] == "none"


def test_a_native_view_with_real_history_of_its_own_keeps_it(report) -> None:
    # The desktop app is the surface that has a second, readable history.
    assert report["back_view_moved"] == "none"
    # A desktop view is always asked first; only one that could not move
    # hands the step back to the chrome.
    assert report["back_view_asks_first"] == "view"
    assert report["back_view_stuck_without_search"] == "none"


def test_a_page_this_chrome_opened_itself_comes_back_before_the_results_do(report) -> None:
    # Results -> a result -> an address typed in the omnibox: the step back is
    # that result, not a jump over it to the results. A cross-origin frame's
    # history cannot be read from here, so the trail this chrome recorded is
    # the only record of where the tab has been.
    assert report["back_trail_before_search"] == "trail"
    assert report["back_trail_without_search"] == "trail"
    # Spent, the trail leaves the results as what is behind the tab.
    assert report["back_trail_spent"] == "search"
    # A desktop view keeps its own history, which is asked first regardless.
    assert report["back_trail_ignored_on_desktop"] == "view"


def test_forward_owes_back_whatever_back_took_you_off(report) -> None:
    # Back to the results is still a step back, so Forward owes the result --
    # otherwise Back is a one-way door and the result you were reading is gone.
    assert report["fwd_ahead_from_results"] == "ahead"
    assert report["fwd_web_with_ahead"] == "ahead"
    # A desktop view is asked first exactly as Back asks it.
    assert report["fwd_view_asks_first"] == "view"
    assert report["fwd_view_answered"] == "none"


def test_a_native_view_that_reported_its_history_is_believed_before_the_click(report) -> None:
    # Asking the view handles a click well enough, but it cannot say anything
    # BEFORE one -- so on the desktop both buttons were lit on every web page
    # and did nothing at the ends of the history. The main process now reports
    # which way the view can move, and the button follows it.
    assert report["back_view_reported_empty"] == "none"
    assert report["back_view_reported_history"] == "view"
    assert report["fwd_view_reported_nothing_ahead"] == "none"
    assert report["fwd_view_reported_something_ahead"] == "view"
    # A view with nothing behind it still owes the results it was opened from.
    assert report["back_view_reported_empty_from_search"] == "search"
    # A desktop build that never reports leaves this undefined, and undefined
    # keeps asking the view -- an older app must not end up with dead buttons.
    assert report["back_view_never_reported"] == "view"
    assert report["fwd_view_never_reported"] == "view"


def test_the_end_of_a_native_view_is_not_the_end_of_the_tab(report) -> None:
    # A WebContentsView holds only the pages opened since it was made, and a
    # results page closes one -- so search from a page, press Back to that
    # page, and the view you land in knows nothing of the results. Asking only
    # the view leaves both buttons dark with a page you were just reading
    # unreachable. The record this chrome kept is asked next, exactly as it is
    # in the plain browser, whether the view answers before the click
    # (canBack/canFwd) or after it (moved).
    assert report["back_view_empty_falls_back_to_trail"] == "trail"
    assert report["back_stuck_view_falls_back_to_trail"] == "trail"
    assert report["fwd_view_empty_falls_back_to_ahead"] == "ahead"
    assert report["fwd_stuck_view_falls_back_to_ahead"] == "ahead"
    # A view that DID move took the step itself; taking a second one off the
    # record would skip a page, which is the other half of the same failure.
    assert report["back_moving_view_leaves_the_trail_alone"] == "none"
    assert report["fwd_moving_view_leaves_the_record_alone"] == "none"


def test_forward_is_dark_where_there_is_nowhere_to_go(report) -> None:
    # The results page can only go forward to a result Back stepped off; with
    # nothing recorded the button is dark rather than lit and inert.
    assert report["fwd_results_with_nothing_ahead"] == "none"
    assert report["fwd_on_new_tab"] == "none"
    assert report["fwd_no_tab"] == "none"


def test_a_second_search_can_be_stepped_back_out_of(report) -> None:
    # Search, then refine the query: the results you refined away from are a
    # page you were just looking at, and Back owes them. Without this the
    # button is dark on the one page this browser renders most often.
    assert report["back_on_results_with_trail"] == "trail"
    assert report["back_on_results_trail_spent"] == "none"
    # A results page owes nothing to a leftover origin: it IS where Back lands.
    assert report["back_on_results_ignores_origin"] == "none"


def test_a_results_page_is_never_answered_as_if_it_were_a_native_view(report) -> None:
    # The desktop app marks a tab native the moment it asks for a view, and the
    # view arrives a round trip later. Search again inside that gap -- click a
    # result, then type a new query -- and the tab shows a results page while
    # still marked native. The results page is rendered by this chrome on every
    # surface, so both buttons read the record this chrome kept; answering
    # "view" there would light Forward with no view to ask, on the one page
    # these steps exist to prove.
    assert report["fwd_on_desktop_results_page"] == "ahead"
    assert report["fwd_on_desktop_results_page_with_nothing_ahead"] == "none"
    assert report["fwd_on_desktop_results_page_stale_report"] == "none"
    assert report["back_on_desktop_results_page"] == "trail"


def test_a_step_records_where_the_page_it_left_belongs(report) -> None:
    a = "thomas://search?q=a"
    # A fresh step leaves that page behind and ends the way ahead -- you
    # cannot go forward into a page you have just navigated away from.
    assert report["record_fresh"] == {"trail": [a], "ahead": []}
    assert report["record_second_search_from_a_result"] == {
        "trail": [a, "https://example.com/a"],
        "ahead": [],
    }
    # A step BACK puts the page ahead instead, so Forward can undo it, and
    # leaves the trail it is walking alone rather than pushing itself onto it.
    assert report["record_back"] == {
        "trail": ["https://example.com/a"],
        "ahead": ["https://example.com/b"],
    }
    # A step FORWARD walks a record that already exists, so it ends nothing.
    assert report["record_forward"] == {"trail": [a], "ahead": ["https://example.com/a"]}


def test_a_page_you_did_not_step_off_is_not_recorded(report) -> None:
    # Reloading is not a step anywhere: it must not stack the same results up
    # behind themselves, and it must not lose the way ahead.
    assert report["record_reload"] == {
        "trail": ["thomas://search?q=b"],
        "ahead": ["https://example.com/a"],
    }
    # A new tab's empty state is not somewhere this browser can return you to.
    assert report["record_new_tab"] == {"trail": [], "ahead": []}


def test_a_native_destination_keeps_no_trail_to_shadow_its_own_history(report) -> None:
    # In the desktop app the page lands in a WebContentsView with a real
    # history, which backStep asks first; a trail here would only shadow it.
    assert report["record_native"] == {"trail": [], "ahead": []}
    assert report["record_native_still_ends_the_way_ahead"] == {"trail": [], "ahead": []}


def test_back_does_nothing_on_a_page_that_is_not_a_web_tab(report) -> None:
    # Results and the new-tab page are where Back points, not what it acts on.
    assert report["back_on_results_page"] == "none"
    assert report["back_on_new_tab"] == "none"
    assert report["back_no_tab"] == "none"


def test_search_from_the_real_chat_shell_opens_a_working_results_tab() -> None:
    """Drive the shipped chat page, its loader, omnibox and Search with a stubbed provider."""
    from tests.web_fixtures.thomas_chat_fixture import browser_ok, open_shell

    if not browser_ok():
        pytest.skip("Chromium unavailable; run the HTML interaction fixture with web.playtest")

    with open_shell("/?browser=1") as shell:
        page = shell.page
        page.route(
            "**/api/search/web?**",
            lambda route: route.fulfill(
                json={
                    "ok": True,
                    "provider": "Fixture provider",
                    "results": [
                        {
                            "title": "Thomas browser documentation",
                            "url": "https://example.com/docs",
                            "snippet": "A real result from the provider boundary.",
                        }
                    ],
                }
            ),
        )
        page.locator("#bt-omni").fill("Thomas browser documentation")
        page.locator("#bt-omni").press("Enter")
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-q").inner_text() == "Results for “Thomas browser documentation”"
        assert page.locator(".bt-sr-title").get_attribute("href") == "https://example.com/docs"
        assert "via Fixture provider" in page.locator(".bt-sr-summary").inner_text()
        assert page.locator("#bt-omni").input_value().startswith("thomas://search?q=")
        # A fresh results page has nowhere to go in either direction, and says
        # so with dark buttons rather than lit ones that do nothing.
        assert page.locator("#bt-back").is_disabled()
        assert page.locator("#bt-fwd").is_disabled()
        with page.expect_request("**/api/search/web?**"):
            page.locator("#bt-reload").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-summary").inner_text() == "1 result · via Fixture provider"
        proof = REPO_ROOT / ".thomas" / "playtest" / "search-real-chat-shell.png"
        proof.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof), full_page=True)
        assert not shell.errors, shell.errors
        page.locator(".bt-sr-title").click()
        assert page.locator("#bt-omni").input_value() == "https://example.com/docs"
        assert page.locator(".bt-web-fallback").count() == 1

        # Back returns to the results. The frame holds one cross-origin entry,
        # so delegating to its history would leave the button lit and inert --
        # which is the state a person reads as a broken browser.
        assert page.locator("#bt-back").is_enabled()
        page.locator("#bt-back").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-q").inner_text() == "Results for “Thomas browser documentation”"
        assert page.locator("#bt-omni").input_value().startswith("thomas://search?q=")
        assert page.locator(".bt-web-fallback").count() == 0
        back = REPO_ROOT / ".thomas" / "playtest" / "search-back-from-result.png"
        page.screenshot(path=str(back), full_page=True)
        assert not shell.errors, shell.errors

        # Results → a result → an address typed in the bar. Back owes that
        # result, and only the step after it owes the results: a browser that
        # skips a page you were just looking at is the same broken feeling as
        # one whose Back does nothing.
        page.locator(".bt-sr-title").click()
        page.locator("#bt-omni").fill("https://example.org/elsewhere")
        page.locator("#bt-omni").press("Enter")
        assert page.locator("#bt-omni").input_value() == "https://example.org/elsewhere"
        page.locator("#bt-back").click()
        assert page.locator("#bt-omni").input_value() == "https://example.com/docs"
        trail = REPO_ROOT / ".thomas" / "playtest" / "search-back-along-the-trail.png"
        page.screenshot(path=str(trail), full_page=True)

        # Forward undoes that step. Without it Back is a one-way door: the
        # address you had just typed would be unreachable.
        page.locator("#bt-fwd").click()
        assert page.locator("#bt-omni").input_value() == "https://example.org/elsewhere"
        page.locator("#bt-back").click()
        assert page.locator("#bt-omni").input_value() == "https://example.com/docs"

        page.locator("#bt-back").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator("#bt-omni").input_value().startswith("thomas://search?q=")

        # The results page is the one page here you arrive at by going back,
        # so it is the one page that can go forward to a result.
        assert page.locator("#bt-back").is_disabled()
        assert page.locator("#bt-fwd").is_enabled()
        forward = REPO_ROOT / ".thomas" / "playtest" / "search-forward-from-results.png"
        page.screenshot(path=str(forward), full_page=True)
        page.locator("#bt-fwd").click()
        assert page.locator("#bt-omni").input_value() == "https://example.com/docs"
        assert page.locator(".bt-web-fallback").count() == 1
        # And that result still owes the results back.
        page.locator("#bt-back").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator("#bt-omni").input_value().startswith("thomas://search?q=")
        assert not shell.errors, shell.errors

        # Refining the query from the results page's own search box. The
        # results you refined away from are a page you were just looking at,
        # so Back owes them -- and Forward owes the refinement.
        first = page.locator(".bt-sr-q").inner_text()
        page.locator(".bt-sr-form input").fill("thomas browser back button")
        page.locator(".bt-sr-form input").press("Enter")
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-q").inner_text() == "Results for “thomas browser back button”"
        assert page.locator("#bt-back").is_enabled()
        refined = REPO_ROOT / ".thomas" / "playtest" / "search-refined-query.png"
        page.screenshot(path=str(refined), full_page=True)
        page.locator("#bt-back").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-q").inner_text() == first
        assert page.locator("#bt-back").is_disabled()
        assert page.locator("#bt-fwd").is_enabled()
        page.locator("#bt-fwd").click()
        page.locator(".bt-sr-title").wait_for(timeout=15000)
        assert page.locator(".bt-sr-q").inner_text() == "Results for “thomas browser back button”"
        assert not shell.errors, shell.errors

        # A site opened straight from the + page has nothing behind it here:
        # its frame was made for that one address, and another origin's history
        # cannot be read from this page at all, so delegating the step is a
        # button that lights up and does nothing. Both stay dark instead.
        page.locator(".bt-newtab").click()
        fresh_box = page.locator(".bt-ntp .bt-bigsearch input").last
        fresh_box.fill("https://example.org/opened-fresh")
        fresh_box.press("Enter")
        page.locator(".bt-web-frame").last.wait_for(state="attached", timeout=15000)
        assert page.locator("#bt-omni").input_value() == "https://example.org/opened-fresh"
        assert page.locator("#bt-back").is_disabled()
        assert page.locator("#bt-fwd").is_disabled()
        fresh = REPO_ROOT / ".thomas" / "playtest" / "search-a-new-tab-has-nothing-behind-it.png"
        page.screenshot(path=str(fresh), full_page=True)
        assert not shell.errors, shell.errors

        # Go somewhere from that tab and the way back appears; come back and the
        # way forward appears with it. Then type a third address: you cannot go
        # forward into a page you have just navigated away from, and the bar has
        # to say so at the moment you type it, not one navigation later.
        page.locator("#bt-omni").fill("https://example.net/second")
        page.locator("#bt-omni").press("Enter")
        assert page.locator("#bt-back").is_enabled()
        assert page.locator("#bt-fwd").is_disabled()
        page.locator("#bt-back").click()
        assert page.locator("#bt-omni").input_value() == "https://example.org/opened-fresh"
        assert page.locator("#bt-fwd").is_enabled()
        page.locator("#bt-omni").fill("https://example.net/third")
        page.locator("#bt-omni").press("Enter")
        assert page.locator("#bt-omni").input_value() == "https://example.net/third"
        assert page.locator("#bt-fwd").is_disabled()
        assert page.locator("#bt-back").is_enabled()
        assert not shell.errors, shell.errors
