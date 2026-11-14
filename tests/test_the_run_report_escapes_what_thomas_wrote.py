"""Everything in the run report is untrusted text rendered into the page.

The report carries filenames, tool output, verification evidence and error
messages â€” all produced by a model or by code it generated, none of it written
by the person reading it. It is built with template strings and assigned via
innerHTML, so an unescaped field is a script tag in the owner's own UI.

Nothing asserted this. It is correct today, and correct-with-no-test is the
state in which a control disappears during an ordinary refactor.

The risk grew concrete on 2026-07-28: the report began carrying the names of
files another code task created. A filename is attacker-influenced in the
weakest sense â€” the model chooses it â€” but "the model chooses it" is exactly
the class of input that should never be trusted into markup.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.web_fixtures.chat_sources import read_chat_sources
from tests.web_fixtures.code_sources import code_function_body, read_code_sources

WEB_JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"
# The report and the artifact cards moved to a sibling module when
# unified_code_mode.js was split. The escaper did NOT move and was not copied:
# it is declared once and injected, which the first test below pins by counting
# declarations across both files. Two escapers is how one of them stops
# escaping.
CODE_JS = WEB_JS / "unified_code_mode.js"
CODE_RESULTS_JS = WEB_JS / "unified_code_results.js"
# Split again: the render cluster left for a size ceiling and took turnHtml,
# eventHtml and replyHtml with it. The escaper still did not move, and the
# declaration count below still spans every module that could redeclare it.
CODE_EVENTS_JS = WEB_JS / "unified_code_events.js"


def _js() -> str:
    return read_code_sources(WEB_JS)


def _function_body(name: str) -> str:
    return code_function_body(WEB_JS, name)


def test_the_escaper_covers_every_dangerous_character() -> None:
    declarations = [line for line in _js().splitlines() if line.strip().startswith("const esc =")]

    assert len(declarations) == 1, "one escaper, shared by injection -- a second copy is one that can drift"
    line = declarations[0]

    for char in ("&", "<", ">", '"', "'"):
        assert char in line, f"{char!r} is not escaped"
    assert "&amp;" in line and "&lt;" in line and "&gt;" in line
    assert "&quot;" in line and "&#39;" in line


def test_every_report_row_field_is_escaped() -> None:
    """Both halves: the heading and the detail. A filename lands in the detail."""
    body = _js().split("function reportRow", 1)[1].split("\n  function", 1)[0]

    assert "esc(heading)" in body
    assert "esc(label)" in body
    assert "${heading}" not in body, "raw interpolation of untrusted text"
    assert "${label}" not in body


def test_the_section_title_is_escaped_too() -> None:
    body = _js().split("function reportSection", 1)[1].split("\n  function", 1)[0]

    assert "esc(title)" in body


def test_every_filename_reaching_the_dom_is_escaped() -> None:
    """Artifact cards carry names Thomas chose, into attributes and text. The
    card markup was rewritten heavily on 2026-07-28 â€” thumbnails, an inline
    stage, a download control, edit-mode identities â€” and each rewrite is a
    chance to interpolate a name raw.

    Audited then: the only bare `${file}` builds a JavaScript key, not markup.
    Every path into the document escapes.

    The 2026-10 Build redesign replaced the card's Download / Open in chat /
    separate-window buttons with one row under the turn (Open in a tab / Keep
    all / Review N files, ThomasCodeCards.artifactActionsHtml); the tab's href
    carries the file name, so it is held to the same rule there."""
    body = code_function_body(WEB_JS, "plainCardHtml")

    for attribute in ("data-code-open-artifact", "data-code-artifact-slot"):
        assert f'{attribute}="${{deps.esc(' in body, f"{attribute} interpolates a filename unescaped"
    live = code_function_body(WEB_JS, "livePreviewHtml")
    assert 'data-live-src="${deps.esc(doc)}"' in live, "a preview URL is interpolated raw into an attribute"
    assert 'href="${deps.esc(href)}"' in live, "the new-tab link interpolates the file URL unescaped"
    assert 'data-code-live="${deps.esc(slot)}"' in live and "${deps.esc(title)}" in live


CHAT_HTML = WEB_JS.parent / "chat.html"


def test_the_code_reply_renders_markdown_through_chats_renderer() -> None:
    """Thomas writes markdown in his Code replies -- 16 of 17 real ones -- and
    this surface printed it raw: "a standalone **Nova** calculator experience in
    `index.html`". The identical prose in Chat rendered properly.

    Reuses Chat's `mdToHtml` rather than copying it, for the same reason there is
    exactly one `esc`: a second implementation is how one of them stops escaping.
    """
    body = _function_body("turnHtml")

    # The reply is now built per outcome (ok / stopped / failed-with-answer),
    # and every branch that carries model prose must still route it through the
    # markdown path: the answer on both outcomes, and the failure note.
    assert "replyBlockHtml(answer" in body, "the model's answer no longer goes through the markdown path"
    assert "replyHtml(failure)" in body, "the failure note no longer goes through the markdown path"
    assert "esc(answer" not in body, "the answer is being double-handled"


def test_progress_notes_use_the_inline_renderer_only() -> None:
    """They render inside a <span>, so block-level output would be invalid there.

    39 of 71 real progress notes carry backticks or bold; only 11% carry bullet
    lines, and a leading "- " left as a literal dash reads fine in prose. The
    inline renderer emits <code>/<strong>/<em>/<a> and nothing else, so it drops
    into the existing markup with no container or stylesheet change.
    """
    body = _function_body("eventHtml")

    assert "progressHtml(label)" in body, "progress notes no longer render their markdown"
    assert "esc(label)" not in body, "a progress note is being escaped twice"

    helper = _function_body("progressHtml")
    assert "mdInline" in helper
    assert "mdToHtml" not in helper, "the block renderer would put <p>/<ul> inside the note's <span>"
    assert "return esc(text)" in helper, "no fallback for a shell-less load"


def test_raw_tool_output_is_never_rendered_as_markdown() -> None:
    """Technical rows carry command output, not prose. Backticks and asterisks in
    a shell line are characters, not formatting, and must stay literal.

    Since the 2026-10 redesign a technical event is drawn as a work row by
    ThomasCodeCards.workRowHtml: the event cluster hands it the raw label as
    TEXT, and the row escapes it into its <pre>. Both halves are pinned."""
    body = _function_body("eventHtml")
    technical = body.split("isTechnicalEvent(event)", 1)[1].split("const label", 1)[0]

    assert "workRowHtml(" in technical
    assert "text: eventLabel(event)" in technical
    assert "progressHtml" not in technical
    assert "replyHtml" not in technical

    row = _function_body("workRowHtml")
    assert "<pre>${esc(full)}</pre>" in row, "the row's full output is not escaped into its body"
    for renderer in ("mdInline", "mdToHtml", "progressHtml", "ThomasMarkdown"):
        assert renderer not in row, f"a work row renders tool output through {renderer}"


def test_the_code_reply_falls_back_to_the_plain_escaper() -> None:
    """The Node contract harness loads this module with no shell around it, so
    `window.ThomasMarkdown` is absent. The reply must still render, escaped."""
    body = _function_body("replyHtml")

    assert "window.ThomasMarkdown" in body
    assert "return esc(text)" in body, "no fallback: a shell-less load would render nothing or throw"


def test_the_markdown_renderer_escapes_before_it_makes_any_tags() -> None:
    """The property the reuse rests on, pinned where it lives.

    `_mdInline` runs `esc` FIRST and only then introduces markup, so untrusted
    model text can never open a tag. Verified live against a reply carrying a
    script tag, an img onerror and a javascript: link: zero script elements, zero
    imgs, no anchor minted, and the tags visible as ordinary characters.

    If this line ever moves after the replacements, both Chat and Code become
    injectable from model output at once.
    """
    text = read_chat_sources(CHAT_HTML)
    body = text.split("function _mdInline", 1)[1].split("function mdToHtml", 1)[0]

    first = next(line.strip() for line in body.splitlines() if line.strip().startswith("s ="))
    assert first == "s = deps.esc(s);", f"escaping is no longer the first step: {first!r}"
    # Links are restricted to http(s), so `javascript:` never becomes an anchor.
    assert "(https?:" in body


def test_the_shared_renderer_is_exported_without_assuming_a_window() -> None:
    """The markdown contract harness evaluates chat.html's script in a VM with no
    `window`; an unguarded assignment took that test down."""
    text = read_chat_sources(CHAT_HTML)

    line = next(ln for ln in text.splitlines() if "window.ThomasMarkdown =" in ln)
    # Both renderers: the block one for replies, the inline one for progress
    # notes, which live inside a <span> and must not receive <p>/<ul>.
    assert "mdToHtml" in line, f"the block renderer is not exported: {line.strip()!r}"
    assert "mdInline" in line, f"the inline renderer is not exported: {line.strip()!r}"
    assert "typeof window !== 'undefined'" in line, f"unguarded export: {line.strip()!r}"


def test_open_risks_reach_the_page_through_that_row() -> None:
    """Pins the path the new provenance risk travels, so a future report
    section cannot render risk details by some other unescaped route."""
    body = _js().split("function runReportHtml", 1)[1].split("\n  function", 1)[0]

    risks_line = next(line for line in body.splitlines() if "open_risks" in line)
    assert "reportRow(" in risks_line
    assert "item.detail" in risks_line
