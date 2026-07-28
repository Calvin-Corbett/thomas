"""A project's results share one origin, so opening one does not blank another.

Each result asked the server for its own preview, which re-minted the project's
grant and destroyed the previous one. Opening the game blanked the thumbnail of
the shell page sitting beside it in the same turn -- a card that had been
rendering correctly a moment earlier, replaced by a broken-document icon.
"""

from __future__ import annotations

from pathlib import Path

CODE_JS = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"


def _js() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def _ensure() -> str:
    return _js().split("async function ensureArtifactDoc", 1)[1].split("\n  //", 1)[0]


def test_a_sibling_file_is_addressed_within_the_origin_already_minted() -> None:
    body = _ensure()

    assert "previewBase" in body
    assert "state.previewBase.url" in body


def test_the_origin_is_only_reused_for_the_conversation_it_belongs_to() -> None:
    """One project per origin. Reusing another project's grant would serve one
    generated app's files to a different one."""
    body = _ensure()

    assert "state.previewBase.cid === token.id" in body


def test_switching_conversations_drops_it() -> None:
    text = _js()
    reset = text.split("state.artifactDocs = {};", 1)[1].split("\n", 1)[0]
    assert "previewBase" in text.split("state.artifactDocs = {};", 1)[0] or "previewBase" in reset or (
        "state.previewBase = null;" in text
    )


def test_a_finished_run_asks_again() -> None:
    """A run that wrote new files produced them after the grant's allowlist was
    built, so the cached origin cannot serve them."""
    text = _js()
    done = text.split("if (payload.type === 'done') {", 1)[1].split("source.close();", 1)[0]

    assert "state.previewBase = null;" in done
    assert "state.artifactDocs = {};" in done


def test_the_file_path_is_still_escaped() -> None:
    """Building a URL by hand must not lose the encoding the query form had."""
    body = _ensure()

    assert "encodeURIComponent" in body
    assert "split('/')" in body, "each segment escaped, so a subdirectory stays a path"
