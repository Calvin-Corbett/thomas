"""A hidden tab stops asking the server, and refreshes the instant it is shown.

Measured in the browser on an idle page (2026-09-08): two panels polled every
1.5s, 79 requests a minute, with nobody touching the page. Every Chat/Build/Work
tab is its own chat.html document, so that figure multiplied by every tab left
open, and the owner's report was "it's running slow, it's not clicking".

Both panels already guarded their poll with ``document.hidden``. That flag is
only true when the whole browser tab is in the background, and the shell hides
an inactive Thomas tab by putting ``bt-doc-hidden`` on that document's <html>
(browser_shell_docs.js, pauseWorld) -- so inside a hidden tab the guard read
false and polling continued at full rate. The mark had exactly one consumer
before this change: a CSS rule that pauses animations. Animations stopped; the
network did not.

What must stay true, and what this test pins:
  - the tab the user is looking at polls exactly as before (no lost freshness);
  - a hidden tab makes no requests at all;
  - being shown again refreshes immediately, not after the idle gap.

The third assertion is the one that keeps this an optimisation rather than a
capability cut: nothing is dropped, only deferred while nobody can see it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "thomas" / "server" / "web" / "js"
DOC_ACTIVITY = WEB_JS / "doc_activity.js"
TODO_PANEL = WEB_JS / "todo_panel.js"
DRIVER = ROOT / "tests" / "web_node" / "hidden_tab_polling.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def report() -> dict:
    out = subprocess.run(
        ["node", str(DRIVER), str(DOC_ACTIVITY), str(TODO_PANEL)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    # The harness prints pretty JSON, so take the whole object, not one line.
    text = out.stdout
    assert "{" in text, f"harness printed no report: {out.stdout!r} {out.stderr!r}"
    return json.loads(text[text.index("{"):])


def test_the_pause_signal_is_actually_read(report: dict) -> None:
    assert report["doc_activity_loaded"] is True
    assert report["paused_after_class"] is True, (
        "bt-doc-hidden on <html> must mean paused; document.hidden alone cannot see it"
    )


def test_a_visible_tab_polls_exactly_as_before(report: dict) -> None:
    """No freshness is taken away from the tab the user is looking at."""
    assert report["visible_fetches_in_10s"] >= 5


def test_a_hidden_tab_asks_for_nothing(report: dict) -> None:
    """The regression this file exists for: hidden documents used to poll forever."""
    assert report["hidden_fetches_in_60s"] == 0


def test_being_shown_again_refreshes_immediately(report: dict) -> None:
    """Deferred, not dropped -- a resumed tab must not wait out the idle gap."""
    assert report["fetches_within_100ms_of_resume"] >= 1


def test_cadence_returns_to_normal_after_resuming(report: dict) -> None:
    assert report["resumed_fetches_in_10s"] >= 5


def test_both_panels_consult_the_shared_pause_signal() -> None:
    """ask_user_panel polls the same way; neither may fall back to document.hidden alone."""
    for name in ("todo_panel.js", "ask_user_panel.js"):
        source = (WEB_JS / name).read_text(encoding="utf-8")
        assert "ThomasDocActivity" in source, f"{name} does not consult the pause signal"
        assert "if (document.hidden) return" not in source, (
            f"{name} still guards on document.hidden, which is false inside a hidden tab"
        )
