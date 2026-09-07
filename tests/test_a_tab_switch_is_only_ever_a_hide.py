"""A tab switch is only ever a hide, proven in a browser.

Calvin's invariant (2026-09-01): one live DOM per tab. Switching shows and hides
persistent containers; drafts, scroll and in-flight streams survive; nothing
re-mounts on a switch. The chat page cannot give a second conversation its own
thread, so a second conversation is a second chat page in its own frame, hidden
with visibility and inert. Every assertion here is a computed style, an object
identity or a request count, never text presence: a whole surface can render
into an invisible element and pass a text check.

Driven against ``tests/web_fixtures/thomas_chat_fixture.py``: the real chat page
and the real shell scripts, every API stubbed, and a reply that drips for three
seconds so a bubble can be watched growing inside a HIDDEN tab.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, open_shell  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

VIS = """(sel) => { const el = document.querySelector(sel); if (!el) return null;
  const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
  return { visibility: cs.visibility, display: cs.display, w: Math.round(r.width), h: Math.round(r.height), inert: !!el.inert }; }"""
TAB_TITLES = "() => Array.from(document.querySelectorAll('.bt-tab .bt-tab-title')).map(e => e.textContent)"
ACTIVE_TITLE = "() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent"
DOC_COUNT = "() => document.querySelectorAll('iframe.bt-doc').length"
GROW = "() => { const b = document.querySelectorAll('#tc-thread .tc-bubble'); return b.length ? b[b.length - 1].textContent.length : 0; }"


@pytest.fixture(scope="module")
def shell():
    with open_shell() as s:
        yield s


def open_row(shell, title: str, ready: int):
    shell.page.click(f'#tc-chats [data-history-title="{title}"]')
    shell.page.wait_for_function(
        f"() => document.querySelectorAll('iframe.bt-doc.is-ready').length >= {ready}", timeout=20000
    )


def test_a_sidebar_row_opens_its_own_document_and_leaves_home_untouched(shell) -> None:
    page = shell.page
    home_thread_before = page.evaluate("() => document.getElementById('tc-thread').childElementCount")
    open_row(shell, "Beta", 1)
    assert page.evaluate(DOC_COUNT) == 1
    src = page.evaluate("() => document.querySelector('iframe.bt-doc').getAttribute('src')")
    assert src.startswith("/?embed=1&browser=0") and "forge_code" not in src
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "visible"
    assert page.evaluate(VIS, "#tc-primary-column")["visibility"] == "hidden"
    assert page.evaluate(VIS, "#tc-primary-column")["inert"] is True
    assert page.evaluate("() => document.querySelector('aside.tc-sidebar').inert") is True
    doc = shell.docs()[0]
    doc.wait_for_function("() => document.getElementById('tc-thread').childElementCount > 0", timeout=20000)
    assert doc.evaluate("() => getComputedStyle(document.querySelector('[data-model-switch]')).display") != "none"  # its own pill
    assert page.evaluate("() => getComputedStyle(document.querySelector('[data-model-switch]')).display") == "none"  # home's pill hides off home
    assert page.evaluate("() => document.getElementById('tc-thread').childElementCount") == home_thread_before
    assert page.evaluate(ACTIVE_TITLE) == "Beta"
    assert page.evaluate(TAB_TITLES) == ["Alpha", "Beta"]  # home learned its restored conversation
    assert not shell.errors, shell.errors


def test_a_draft_and_the_scroll_position_survive_a_switch_away_and_back(shell) -> None:
    page = shell.page
    doc = shell.docs()[0]
    doc.fill("#tc-input", "draft that must survive")
    doc.evaluate("() => { document.getElementById('tc-scroll').scrollTop = 300; }")
    identity = doc.evaluate("() => { window.__ident = Math.random(); return window.__ident; }")
    page.click(".bt-tab.is-pinned")
    page.fill("#tc-input", "home draft too")  # home is the visible surface now
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "hidden"
    assert page.evaluate("() => document.querySelector('iframe.bt-doc').inert") is True
    assert doc.evaluate("() => document.documentElement.classList.contains('bt-doc-hidden')") is True
    paused = "() => getComputedStyle(document.querySelector('.tc-world *')).animationPlayState"
    assert doc.evaluate(paused) == "paused"
    assert page.evaluate(VIS, "#tc-primary-column")["visibility"] == "visible"
    page.keyboard.press("Control+2")
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "visible"
    assert doc.evaluate("() => window.__ident") == identity
    assert doc.evaluate("() => document.getElementById('tc-input').value") == "draft that must survive"
    assert doc.evaluate("() => document.getElementById('tc-scroll').scrollTop") == 300
    assert page.evaluate("() => document.getElementById('tc-input').value") == "home draft too"
    assert doc.evaluate(paused) == "running"


def test_a_reply_keeps_streaming_while_its_tab_is_hidden(shell) -> None:
    page = shell.page
    doc = shell.docs()[0]
    doc.fill("#tc-input", "stream while hidden")
    doc.press("#tc-input", "Enter")
    page.wait_for_timeout(500)
    page.click(".bt-tab.is-pinned")
    page.wait_for_timeout(700)
    first = doc.evaluate(GROW)
    light = "() => document.querySelectorAll('.bt-tab')[1].querySelector('.bt-light').classList.contains('working')"
    assert page.evaluate(light) is True
    page.wait_for_timeout(1200)
    assert doc.evaluate(GROW) > first
    doc.wait_for_function(
        "() => !document.querySelector('.tc-mode-button[data-thomas-mode=chat]').hasAttribute('data-running')",
        timeout=15000,
    )
    assert shell.fixture.chat_calls == 1
    assert "[stopped]" not in doc.evaluate("() => document.getElementById('tc-thread').textContent")
    assert page.evaluate(light) is False


def test_closing_a_document_tab_removes_it_and_the_home_tab_cannot_be_closed(shell) -> None:
    page = shell.page
    page.click(".bt-tab:not(.is-pinned) .bt-tab-x")
    assert page.evaluate(DOC_COUNT) == 0
    assert page.evaluate(TAB_TITLES) == ["Alpha"]
    assert page.evaluate(VIS, ".bt-tab.is-pinned .bt-tab-x")["display"] == "none"
    page.keyboard.press("Control+w")
    assert page.evaluate(TAB_TITLES) == ["Alpha"]
    assert page.evaluate(VIS, "#tc-primary-column")["visibility"] == "visible"
    assert not shell.errors, shell.errors
