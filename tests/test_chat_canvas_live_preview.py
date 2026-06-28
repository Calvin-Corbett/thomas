from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"


def test_chat_canvas_live_mode_renders_streaming_html_preview() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "function _livePreviewHtml(html, done)" in text
    assert "function _closePartialHtml(html)" in text
    assert "Receiving HTML" in text
    assert "liveFrame.setAttribute('srcdoc', _livePreviewHtml(canvasState.html || '', !canvasState.live));" in text
