"""A search result whose link goes to the search engine is not a result.

The DuckDuckGo fallback returns `//duckduckgo.com/l/?uddg=<encoded>` redirect
wrappers rather than destinations. Rendered as-is they look like ordinary
links and navigate somewhere else entirely, which is both broken and
dishonest -- the page would be showing a URL it is not going to open.

These pin the unwrapping. The endpoint itself needs a network and a provider,
so what is tested here is the pure part that can be wrong silently.
"""

from __future__ import annotations

from thomas.server.routes.search import _result_url


def test_a_redirect_wrapper_is_unwrapped_to_its_destination() -> None:
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.electronjs.org%2Fdocs%2Flatest"
    assert _result_url(wrapped) == "https://www.electronjs.org/docs/latest"


def test_a_protocol_relative_url_gets_a_scheme() -> None:
    assert _result_url("//example.com/thing") == "https://example.com/thing"


def test_an_ordinary_url_is_left_exactly_alone() -> None:
    for url in (
        "https://www.electronjs.org/docs/latest/api/web-contents-view",
        "http://electronproject.org/web-contents-view.html",
        "https://example.com/a?b=c&d=e#frag",
    ):
        assert _result_url(url) == url


def test_nothing_in_never_becomes_something_out() -> None:
    for empty in ("", None, "   "):
        assert _result_url(empty) in ("", "")


def test_a_lookalike_host_is_not_treated_as_a_wrapper() -> None:
    """Only duckduckgo's own /l/ path is a wrapper."""
    url = "https://notduckduckgo.com.evil.example/l/?uddg=https%3A%2F%2Fevil.example"
    assert _result_url(url) == url


def test_a_result_that_is_not_a_web_address_is_dropped() -> None:
    """Escaping an href stops attribute injection, not a scheme.

    The redirect wrapper's target is chosen by whoever ranks for the query, so
    ``javascript:`` survives unwrapping unchanged and would land in the chrome
    document as a clickable link -- the document that holds the desktop
    bridge. An empty string is the honest answer: it drops the row.
    """
    assert _result_url("javascript:alert(1)") == ""
    assert _result_url("//duckduckgo.com/l/?uddg=javascript%3Aalert(1)") == ""
    assert _result_url("data:text/html,<script>alert(1)</script>") == ""
    assert _result_url("file:///C:/Windows/System32/config") == ""
    # ...and an ordinary result still comes through untouched.
    assert _result_url("https://example.com/a") == "https://example.com/a"
