"""A generated app that embeds its own page must render, not be refused.

Thomas built a roguelite as a shell `index.html` framing `trey-badlands.html`.
The shell loaded; the game inside it did not, and the card showed a broken
document icon -- indistinguishable, on screen, from Thomas having written a
broken game. The browser said exactly what happened:

    Framing 'http://127.0.0.1:64872/' violates the following Content Security
    Policy directive: "frame-ancestors http://127.0.0.1:8899"

`frame-ancestors` is checked against the WHOLE ancestor chain, not just the
immediate parent. The inner frame's chain is [preview origin, Thomas UI], and
only the UI was named.
"""

from __future__ import annotations

from aiohttp import web

from thomas.server.routes.deliverable_aiohttp import DeliverablePreviewService


def _csp(main_origin: str) -> str:
    service = DeliverablePreviewService()
    if main_origin:
        service.configure(main_origin=main_origin)
    response = web.Response(text="")
    service._apply_headers(response)
    return response.headers["Content-Security-Policy"]


def _frame_ancestors(main_origin: str = "http://127.0.0.1:8899") -> str:
    directive = next(
        part for part in _csp(main_origin).split(";") if part.strip().startswith("frame-ancestors")
    )
    return directive.strip()


def test_an_app_may_frame_its_own_pages() -> None:
    assert "'self'" in _frame_ancestors()


def test_the_thomas_ui_may_still_frame_the_preview() -> None:
    assert "http://127.0.0.1:8899" in _frame_ancestors()


def test_nothing_else_may_frame_it() -> None:
    """'self' is one app's OWN origin. Each grant listens on its own ephemeral
    port, so this grants nothing to another preview or to a remote page -- which
    a wildcard like 127.0.0.1:* would have done."""
    ancestors = _frame_ancestors()

    assert "*" not in ancestors
    assert "http:" not in ancestors.replace("http://127.0.0.1:8899", "")
    assert set(ancestors.split()[1:]) == {"http://127.0.0.1:8899", "'self'"}


def test_an_unconfigured_service_frames_nowhere() -> None:
    """Before the UI origin is known, refusing every framer is the safe default;
    'self' must not weaken that into a usable preview."""
    assert _frame_ancestors("") == "frame-ancestors 'none'"


def test_the_generated_code_is_still_sandboxed() -> None:
    """Being framable by itself must not relax what the code inside can do."""
    csp = _csp("http://127.0.0.1:8899")

    assert "sandbox allow-scripts allow-forms allow-same-origin" in csp
    assert "allow-top-navigation" not in csp
    assert "allow-popups" not in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
