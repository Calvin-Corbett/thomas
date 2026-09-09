from __future__ import annotations

import re

from tests.web_ui_source import read_app_js_source


def test_web_ui_chat_rendering_keeps_xss_guards_in_place():
    app_js = read_app_js_source()
    assert "renderer.html" in app_js
    assert "sanitizeRenderedHtml" in app_js
    assert "sanitizeUrl" in app_js
    assert "insertAdjacentHTML('beforeend', html)" not in app_js

    attachments_fn = re.search(
        r"function renderAttachmentsPreview\(\)\s*\{[\s\S]*?\n\}",
        app_js,
    )
    assert attachments_fn is not None
    assert ".innerHTML" not in attachments_fn.group(0)
