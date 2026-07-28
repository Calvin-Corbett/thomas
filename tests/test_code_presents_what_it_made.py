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


def test_a_result_opens_in_the_conversation_not_a_side_panel() -> None:
    """Sending the result to a side panel is still telling someone where to go
    and look. Chat puts a deliverable in the thread; Code is meant to be Chat
    that builds rather than dispatches."""
    text = _js()
    handler = text.split("data-code-open-artifact]").pop().split("});", 1)[0]

    assert "artifactOpen" in handler, "opening must expand in the thread"
    assert "drawerOpen" not in handler, "a result must not be pushed to the side panel"
    assert "ensureArtifactDoc" in handler


def test_each_turn_opens_its_own_copy() -> None:
    """The same file is listed by every turn that touched it, so keying the open
    state by name alone opened six copies of the game from one click."""
    text = _js()

    assert "data-code-artifact-slot" in text
    assert "${turnKey}::${file}" in text


def test_a_result_shows_a_live_thumbnail() -> None:
    """You can see what it is before deciding to open it, the way Chat does."""
    text = _js()
    body = text.split("function artifactCardsHtml", 1)[1].split("\n  function", 1)[0]

    assert "tc-code-artifact-thumb" in body
    assert "srcdoc=" in body


def test_thumbnails_are_loaded_without_being_asked_and_are_capped() -> None:
    text = _js()

    assert "hydrateArtifactThumbnails" in text
    assert "_ARTIFACT_THUMB_BUDGET" in text


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
