"""The file card's download CTA must contain its text; its preview must speak
the user's language.

Measured (2026-08-05, live): "Download packing.txt" rendered as text wrapping
OUT of a 42px icon button. The anchor hides its spoken label in a
``class="sr-only"`` span, but the only stylesheet defining ``.sr-only``
(css/accessibility.css) is never linked by chat.html -- so the "hidden" label
was fully visible, crammed into a box sized for one icon. In the same card the
secondary action read "Open UTF-8 preview" -- encoding jargon for "Preview".

The harness (tests/web_node/chat_artifact_card_cta.mjs) renders the real
``artifactHTML`` at a normal and a long filename and pins:

* every download anchor's only visible content is the icon; the filename label
  lives in an ``sr-only`` span (screen readers still hear "Download <name>"),
* chat.html itself defines a ``.sr-only`` rule, so the span is actually hidden
  on this page rather than only on pages that happen to link accessibility.css,
* the secondary action says "Preview", with no "UTF-8" anywhere on the card,
* the long filename stays ellipsized inside the card body.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_artifact_card_cta.mjs"


def test_the_download_button_is_an_icon_and_the_preview_is_a_word() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_HTML)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout)
    assert checks and all(checks.values()), checks
