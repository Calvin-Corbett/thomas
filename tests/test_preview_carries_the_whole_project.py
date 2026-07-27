"""A multi-file build must preview complete, not as the page minus its parts."""

from __future__ import annotations

import re
from pathlib import Path

CODE_JS = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"


def _js() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def _inliner() -> str:
    return _js().split("async function inlineLocalAssets", 1)[1].split("\n  async function", 1)[0]


def test_a_referenced_local_script_is_carried_into_the_preview() -> None:
    """srcdoc has NO project base URL, so a relative <script src="renderer.js">
    resolves against the Thomas server and 404s. Thomas had just split a game's
    chase-camera renderer into its own file; without this the game previewed as
    a game with no renderer, which looks exactly like the renderer not working.
    """
    text = _js()

    assert "inlineLocalAssets" in text
    body = _inliner()
    assert "<script" in body and "src" in body
    assert "inlined from" in body, "the substitution should be visible in the document"


def test_stylesheets_are_carried_too() -> None:
    body = _inliner()
    assert "link" in body and "<style>" in body


def test_remote_urls_are_left_alone() -> None:
    """A CDN reference is not ours to inline, and the sandbox has no
    same-origin, so leaving it is both correct and safe."""
    body = _inliner()
    assert "isLocal" in body
    assert re.search(r"\[a-z\]\+:\)\?\\/\\/|\/\/", body), "no remote-URL guard"
    assert "data:" in body


def test_assets_are_read_through_the_same_validated_endpoint() -> None:
    """No new route and no new path-traversal surface: the referenced files come
    back through the identical read that served the page."""
    text = _js()
    reader = text.split("function readProjectFile", 1)[1].split("\n  //", 1)[0]

    assert "/api/evolve/agent/conversations/" in reader
    assert "encodeURIComponent" in reader
    assert "/file?path=" in reader


def test_a_missing_asset_does_not_lose_the_preview() -> None:
    """One unreadable dependency must not cost the whole page."""
    body = _inliner()
    assert "=== null" in body or "!== null" in body, "a failed read must be skipped, not fatal"


def test_only_pages_are_processed() -> None:
    text = _js()
    load = text.split("async function loadFile", 1)[1]
    assert re.search(r"\.x\?html\?\$", load) or ".x?html?$" in load
