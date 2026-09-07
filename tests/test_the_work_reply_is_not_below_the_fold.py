"""Work onboarding: the reply must fit the panel it renders in (2026-09-06).

Driving Work as a user on a short window: the job was typed, Thomas mapped it
and answered, and the page showed only the user's own words. The transcript
carried a fixed 360px minimum height that beat its viewport-fitting maximum,
so in a 611px frame the reply and the "Choose one workflow" chooser sat below
the panel's visible bottom. The chooser's buttons had no rules at all: the
workflow name ran straight into its purpose in a default grey box.

The scroll half lives in unified_work_mode.js, held by another agent; this
file pins the CSS half.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "thomas" / "server" / "web" / "css"


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"no rule for {selector}"
    return match.group(1)


def test_the_transcript_minimum_height_yields_to_a_short_viewport() -> None:
    css = (CSS / "unified_work_mode.css").read_text(encoding="utf-8")
    body = _rule(css, ".tc-work-transcript")
    height = re.search(r"min-height:\s*([^;]+);", body)
    assert height, body
    assert "min(" in height.group(1) and "100vh" in height.group(1), height.group(1)


def test_the_workflow_chooser_buttons_are_styled_as_choices() -> None:
    css = (CSS / "unified_work_details.css").read_text(encoding="utf-8")
    button = _rule(css, ".tc-work-onboarding-map button")
    assert "text-align: left" in button and "border-radius" in button
    name = _rule(css, ".tc-work-onboarding-map button strong")
    purpose = _rule(css, ".tc-work-onboarding-map button span")
    assert "display: block" in name and "display: block" in purpose
    assert "text-align: right" not in purpose
