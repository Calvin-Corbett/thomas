"""Thomas must hand back what he made, not describe where it went."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web"
CODE_JS = WEB / "js" / "unified_code_mode.js"
# The artifact cards, their preview documents and the run report live in the
# sibling module the browser loads immediately before unified_code_mode.js.
# Read as one text because the guarantees below are about the Code client as the
# browser assembles it, not about which of its two files a line sits in.
CODE_RESULTS_JS = WEB / "js" / "unified_code_results.js"
CODE_CSS = WEB / "css" / "unified_code_activity.css"
CODE_RESULTS_CSS = WEB / "css" / "unified_code_results.css"


def _js() -> str:
    return CODE_JS.read_text(encoding="utf-8") + "\n" + CODE_RESULTS_JS.read_text(encoding="utf-8")


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
    """You can see what it is before deciding to open it, the way Chat does.

    The thumbnail is loaded from a real preview origin rather than srcdoc.
    srcdoc has no origin and no base URL, so a page that loads anything at
    runtime -- a renderer module, a sprite sheet -- previewed as that page with
    the parts missing, which looks exactly like the parts being broken.
    """
    text = _js()
    body = text.split("function artifactCardsHtml", 1)[1].split("\n  }\n", 1)[0]

    assert "tc-code-artifact-thumb" in body
    assert "srcdoc=" not in body, "srcdoc cannot load what the page references"
    assert "src=" in body


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


def test_the_viewer_makes_room_instead_of_covering_the_conversation() -> None:
    """The card says "Click to open it beside the chat". It opened over it.

    `.tc-code-viewer` is `position: absolute`, so opening it moved nothing.
    Measured at 1920 wide: the transcript stayed 768px at x=716 while the viewer
    covered from x=1160 -- 324px of the conversation underneath it, clipping
    300px off every line of Thomas's reply, mid-word ("correct running b").

    After: transcript at x=336, right edge 1104, viewer at 1160. Zero overlap.
    """
    js = _js()
    css = CODE_CSS.read_text(encoding="utf-8")

    assert "is-viewer-open" in js, "the panel no longer marks an open viewer"
    assert ".tc-code-panel.is-viewer-open .tc-code-layout" in css, (
        "nothing reserves room for the viewer, so it covers the conversation again"
    )
    reserve = css.split(".tc-code-panel.is-viewer-open .tc-code-layout", 1)[1].split("}", 1)[0]
    assert "padding-right" in reserve
    # The same width the viewer itself uses, or the reservation is a guess.
    viewer_width = css.split(".tc-code-viewer {", 1)[1].split("}", 1)[0]
    assert "min(760px, 62vw)" in viewer_width
    assert "min(760px, 62vw)" in reserve, "the reserved width does not match the viewer's"


def test_a_full_bleed_viewer_does_not_reserve_room_behind_itself() -> None:
    """It covers the surface deliberately then; squeezing a layout nobody can see
    would only make reopening it jump."""
    js = _js()

    marker = js.split("is-viewer-open", 1)[0]
    assert "viewerFull" in marker or "viewerFull" in js, "the full-bleed case is not distinguished"
    line = next(ln for ln in js.splitlines() if "is-viewer-open" in ln and "class=" in ln)
    assert "!viewerFull" in line, f"full-bleed still reserves room: {line.strip()[:120]!r}"


def _css_block(css: str, selector: str) -> str:
    return css.split(selector, 1)[1].split("}", 1)[0]


def test_a_previewed_file_is_a_miniature_not_a_keyhole() -> None:
    """Clicking a file in the drawer tree rendered the page 1:1 into a ~247px
    column: "Sort by amount" cut to "Sort by", the header row reading
    "DATE DESCRIPTION AM…", about a fifth of the page visible and every edge
    sliced mid-word.

    The artifact thumbnail had this exact bug and was fixed; this is a different
    element, so the fix never reached it.
    """
    js = _js()
    css = CODE_RESULTS_CSS.read_text(encoding="utf-8")

    assert "tc-code-file-shot" in js, "the file preview no longer wraps its frame"
    assert 'style="width:100%;height:320px' not in js, (
        "the preview iframe is inline-sized again, which is what produced the keyhole"
    )
    assert ".tc-code-file-shot {" in css
    box = _css_block(css, ".tc-code-file-shot {")
    assert "overflow: hidden" in box
    frame = _css_block(css, ".tc-code-file-shot iframe {")
    assert "transform: scale(" in frame


def test_the_preview_scale_actually_fits_the_box() -> None:
    """The invariant the whole thing rests on: the document width times the
    scale must equal the box width. Get that wrong and it is a keyhole again --
    the same defect wearing a transform."""
    css = CODE_RESULTS_CSS.read_text(encoding="utf-8")

    for box_sel, frame_sel in (
        (".tc-code-file-shot {", ".tc-code-file-shot iframe {"),
        (".tc-code-artifact-shot {", ".tc-code-artifact-shot iframe {"),
    ):
        box = _css_block(css, box_sel)
        frame = _css_block(css, frame_sel)
        box_w = int(re.search(r"width:\s*(\d+)px", box).group(1))
        doc_w = int(re.search(r"width:\s*(\d+)px", frame).group(1))
        scale = float(re.search(r"scale\(([\d.]+)\)", frame).group(1))
        assert abs(doc_w * scale - box_w) <= 2, (
            f"{box_sel} draws a {doc_w}px document at {scale} into a {box_w}px box "
            f"-> {doc_w * scale:.1f}px, so it is cropped, not scaled"
        )
        assert doc_w > box_w, f"{frame_sel} is not rendering a full-width page"
