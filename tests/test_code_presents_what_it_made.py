"""Thomas must hand back what he made, not describe where it went."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web"
CODE_JS = WEB / "js" / "unified_code_mode.js"
CODE_CSS = WEB / "css" / "unified_code_activity.css"


def _js() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def test_a_finished_build_names_what_it_produced() -> None:
    """The whole delivery used to be the words "1 result ready" -- a count, with
    no name and nothing to click. After Thomas built a working game the next two
    messages from the owner were "where is iut" and "whatsbthe full
    doiretcoyur name". The turn already carried
    artifacts:[{file:'trey-badlands.html',kind:'html'}] the entire time.
    """
    text = _js()

    assert "artifactCardsHtml" in text
    assert "data-code-open-artifact" in text
    assert "tc-code-artifact-name" in text, "the file must be named, not counted"


def test_the_bare_result_count_is_gone() -> None:
    """A count is not a delivery."""
    text = _js()
    assert not re.search(r"result\$\{resultCount === 1 \? '' : 's'\} ready", text)
    assert "results ready" not in text


def test_a_page_opens_playable_rather_than_as_source() -> None:
    text = _js()
    handler = text.split("data-code-open-artifact]").pop().split("});", 1)[0]

    assert "filePreviewRendered = true" in handler, "a page must open rendered"
    assert "loadFile" in handler


def test_a_finished_run_presents_its_result_without_being_asked() -> None:
    text = _js()

    assert "presentNewestResult" in text
    body = text.split("async function presentNewestResult", 1)[1].split("\n  }", 1)[0]
    assert "role !== 'agent'" in body, "only a Thomas turn produces a result"
    assert "turn.ok" in body, "a failed run has nothing to present"
    assert re.search(r"\.x\?html\?\$", body) or ".x?html?$" in body, "prefer a page"


def test_the_card_is_a_real_control() -> None:
    css = CODE_CSS.read_text(encoding="utf-8")

    assert ".tc-code-artifact-open" in css
    assert "cursor: pointer" in css
    assert ":focus-visible" in css, "it must be reachable from the keyboard"
    assert css.count("{") == css.count("}"), "unbalanced CSS"


def test_internal_paths_are_not_offered_as_results() -> None:
    text = _js()
    body = text.split("function artifactCardsHtml", 1)[1].split("\n  }", 1)[0]

    assert "isInternalResultPath" in body
