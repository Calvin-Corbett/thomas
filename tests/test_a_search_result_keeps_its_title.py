"""A search result has to survive the markup it was parsed out of.

The DuckDuckGo fallback returned rows whose title was a bare URL and whose
snippet was that same URL again -- a results page built on those rows would
have looked broken next to any real search engine. The cause was in the
parser, not in the absence of a Brave key: DuckDuckGo nests several elements
whose class names all *contain* "result" inside each result, and a substring
test treated each of them as the start of a new result, discarding the title
and snippet that had already been collected. The last thing standing when the
result closed was the displayed-URL anchor, so that is what came out.

These tests feed the parser markup shaped like the real page and assert on
what a person would see on the page: a headline, a description, and a link.
"""

from __future__ import annotations

from thomas.tools.web_search_parsing import _DDGHtmlResultsParser

# Shaped after html.duckduckgo.com: an outer .result, an inner .result__body,
# the title anchor, the snippet anchor, and a .result__extras block holding a
# second anchor that carries the *displayed* url rather than the destination.
SERP = """
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.electronjs.org%2Fdocs%2Flatest%2Fapi%2Fweb-contents-view">
        WebContentsView | Electron
      </a>
    </h2>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.electronjs.org%2F">
      A View that displays a WebContents. Process: Main. This class is not exported.
    </a>
    <div class="result__extras">
      <div class="result__extras__url">
        <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.electronjs.org%2F">
          www.electronjs.org/docs/latest/api/web-contents-view
        </a>
      </div>
    </div>
  </div>
</div>
"""


def _parse(html: str) -> list[dict]:
    parser = _DDGHtmlResultsParser()
    parser.feed(html)
    parser.close()
    return parser.results


def test_the_title_is_the_headline_not_the_displayed_url() -> None:
    rows = _parse(SERP)
    assert len(rows) == 1, f"expected one result, parsed {len(rows)}: {rows}"
    assert rows[0]["title"] == "WebContentsView | Electron"


def test_the_snippet_describes_the_page_rather_than_repeating_the_title() -> None:
    rows = _parse(SERP)
    desc = rows[0]["description"]
    assert desc.startswith("A View that displays a WebContents")
    assert desc != rows[0]["title"]


def test_the_displayed_url_anchor_does_not_leak_into_the_title() -> None:
    # The regression that shipped: .result__url's text was appended to, and in
    # practice replaced, the headline.
    rows = _parse(SERP)
    assert "electronjs.org/docs" not in rows[0]["title"]


def test_nested_result_classes_do_not_split_one_result_into_many() -> None:
    # .result__body, .result__extras and .result__extras__url all contain the
    # substring "result"; none of them starts a new result.
    assert len(_parse(SERP + SERP)) == 2


def test_a_result_container_named_web_result_still_starts_a_result() -> None:
    # Some DuckDuckGo variants label the container without a bare "result"
    # token, so the opening test cannot be an exact token match either.
    html = """
    <div class="web-result">
      <div class="result__body">
        <h2><a class="result__a" href="https://example.com/a">Example Domain</a></h2>
        <a class="result__snippet">An example page.</a>
      </div>
    </div>
    """
    rows = _parse(html)
    assert len(rows) == 1
    assert rows[0]["title"] == "Example Domain"


def test_a_result_with_no_snippet_still_parses() -> None:
    html = """
    <div class="result">
      <div class="result__body">
        <h2><a class="result__a" href="https://example.com/b">Bare Result</a></h2>
      </div>
    </div>
    """
    rows = _parse(html)
    assert len(rows) == 1
    assert rows[0]["title"] == "Bare Result"
