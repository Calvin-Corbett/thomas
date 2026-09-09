"""A canvas deliverable must not be blank when its script does not run."""

from __future__ import annotations

import json
import re

from thomas.server.chat_delegation_canvas import build_canvas_html


def _spec() -> str:
    return json.dumps(
        {
            "stage": {"w": 720, "h": 520, "bg": "#ffffff"},
            "title": "Quarterly Revenue",
            "elements": [
                {
                    "id": "t",
                    "kind": "text",
                    "label": "Quarterly Revenue",
                    "geometry": {"x": 40, "y": 40, "size": 28},
                    "sequence": {"order": 1},
                },
                {
                    "id": "n",
                    "kind": "number",
                    "value": 135,
                    "geometry": {"x": 40, "y": 200, "size": 30},
                    "sequence": {"order": 2},
                },
            ],
        }
    )


def _html() -> str:
    return build_canvas_html(_spec())


def test_a_scriptless_render_is_not_a_blank_page() -> None:
    """The document ships data-reveal="pending", which holds every element at
    opacity 0 behind an opaque cover, and only JS flips it to "play". Without
    the noscript escape hatch a reader with scripting unavailable -- a strict
    CSP, a sandboxed frame, a preview pane -- gets a blank white page and no
    indication anything is wrong."""
    html = _html()
    noscript = re.search(r"<noscript>(.*?)</noscript>", html, re.S)

    assert noscript, "canvas deliverable has no scriptless fallback"
    body = noscript.group(1)
    assert "opacity:1 !important" in body
    assert "#tc-stage::after{opacity:0 !important}" in body
    # Load-bearing: .el transitions opacity, so declaring the final value merely
    # STARTS a transition toward it, and a transition only advances while the
    # document's animation timeline runs. In a background or throttled tab the
    # timeline is frozen and the element stays at 0 -- blank, via a rule that
    # says opacity:1 !important. Measured on a real pending document: without
    # this line 0 of 10 elements became visible, with it all 10 did.
    assert "transition:none !important" in body


def test_numbers_ship_their_real_value_not_zero() -> None:
    """Without the script a count-up used to render its placeholder, so every
    value on a chart read 0 -- worse than blank, because it is confidently
    wrong."""
    html = _html()
    number_div = re.search(r'<div class="el count-up"[^>]*>([^<]*)</div>', html)

    assert number_div, "no count-up element rendered"
    assert number_div.group(1) == "135"
    assert 'data-count="135"' in html


def test_the_script_still_starts_the_count_from_zero() -> None:
    """Shipping the real value must not cause a flash of the answer before the
    animation: the script zeroes every count-up at end of body, before paint."""
    html = _html()

    assert "[data-count]" in html
    assert "el.textContent='0'" in html


def test_the_noscript_block_is_inert_when_scripting_works() -> None:
    """It must be a <noscript> block, not a plain style -- otherwise it would
    override the animation for everyone and there would be no reveal at all."""
    html = _html()
    fallback = re.search(r"<noscript>.*?</noscript>", html, re.S)

    assert fallback
    # The always-on stylesheet must still hide pending elements, or the
    # animation has been destroyed for scripted readers.
    always_on = html[: html.index("<noscript>")]
    assert "[data-reveal='pending'] .rise-fade" in always_on
    assert "opacity:0" in always_on
