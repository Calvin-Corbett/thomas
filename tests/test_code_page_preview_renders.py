"""A generated page is previewed rendered, and sandboxed so it cannot reach Thomas."""

from __future__ import annotations

import re
from pathlib import Path

CODE_MODE_JS = Path(__file__).resolve().parent.parent / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"


def _source() -> str:
    return CODE_MODE_JS.read_text(encoding="utf-8")


def test_an_html_file_is_previewed_as_a_rendered_page() -> None:
    """Code mode showed generated pages as source in a <pre>. Watching a game or
    a site take shape is the point of building one."""
    text = _source()

    assert "srcdoc=" in text
    assert re.search(r"\\.x\?html\?\$", text) or ".x?html?$" in text, "no html detection"


def test_the_preview_iframe_never_gets_same_origin() -> None:
    """srcdoc inherits THIS page's origin. With allow-same-origin a generated
    app could read Thomas's own storage and call its API as the user. Scripts
    are allowed so games and animations run; same-origin is not, which also
    means localStorage is unavailable inside the preview."""
    text = _source()
    # Only srcdoc frames. An iframe pointed at the separate ephemeral preview
    # ORIGIN may legitimately carry allow-same-origin -- that origin is not
    # Thomas. srcdoc has no origin of its own, so it borrows this page's.
    srcdoc_frames = [m for m in re.findall(r"<iframe[^>]*>", text) if "srcdoc=" in m]

    assert srcdoc_frames, "the rendered page preview must be a srcdoc iframe"
    for frame in srcdoc_frames:
        sandbox = re.search(r'sandbox="([^"]*)"', frame)
        assert sandbox, f"srcdoc frame without a sandbox: {frame[:80]}"
        assert "allow-same-origin" not in sandbox.group(1), f"unsafe: {sandbox.group(1)!r}"


def test_the_live_refresh_never_opens_a_preview_by_itself() -> None:
    """It refreshes what is already open. Popping a preview open mid-run would
    steal the panel while someone is reading something else."""
    text = _source()
    body = text.split("function refreshOpenPagePreview", 1)[1].split("function pushLiveEvent", 1)[0]

    assert "if (!open" in body, "must bail when nothing is open"
    assert "state.filePreviewRendered === false" in body, "must respect the code/page toggle"


def test_the_live_refresh_is_throttled() -> None:
    """Run events arrive in bursts; re-reading the file on every one would hammer
    the endpoint."""
    body = _source().split("function refreshOpenPagePreview", 1)[1].split("function pushLiveEvent", 1)[0]

    assert "_previewRefreshAt" in body
    assert re.search(r"<\s*1500", body), "no throttle interval"


def test_you_can_still_read_the_source() -> None:
    text = _source()
    assert "data-code-preview-toggle" in text
    assert "Show code" in text and "Show page" in text
