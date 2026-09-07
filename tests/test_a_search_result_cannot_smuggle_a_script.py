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

pytestmark = pytest.mark.skipif(
    not SEARCH_JS.exists(), reason="browser shell is not present in this checkout"
)


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
