"""A preview that blocks a page's network calls must say so on its face.

Measured (w2-code-network, w2-code-impossible): the artifact preview CSP kills
any outbound connection beside the chat, so the owner's first sight of a
perfectly working generated app is its own error state -- "Live feed
unavailable", "Google sign-in is still loading" -- with nothing anywhere saying
the PREVIEW is the reason. The app was correct; the surface it was handed back
on was the thing refusing, silently.

The fix is sight, not a gate: the viewer scans the page it already reads and
puts one visible line on the surface -- the embedded preview blocks internet
access, open it in its own tab for live data -- beside the open-in-tab
affordance that already exists. Driven through
``tests/web_node/code_preview_network_notice.mjs`` against the real
``unified_code_results.js``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_preview_network_notice.mjs"


def _drive() -> dict[str, bool]:
    result = subprocess.run(
        ["node", str(HARNESS), str(RESULTS_JS)],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and any em dash in the wording arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_viewer_knows_a_network_shaped_page_when_it_reads_one() -> None:
    report = _drive()
    for check in (
        "detectorExported",
        "flagsFetch",
        "flagsRelativeFetch",
        "flagsXhr",
        "flagsWebSocket",
        "flagsEventSource",
        "flagsExternalScript",
        "flagsExternalStylesheet",
        "flagsExternalImage",
    ):
        assert report[check], check


def test_a_self_contained_page_is_not_nagged() -> None:
    report = _drive()
    assert report["quietOnPlainPage"]
    assert report["quietOnProseAndLinks"]
    assert report["quietFlagLearned"]
    assert report["noNoticeOnQuietPage"]


def test_the_notice_reaches_the_viewer_surface_beside_the_way_out() -> None:
    report = _drive()
    assert report["docResolved"]
    assert report["networkFlagLearned"]
    assert report["noticeShown"]
    assert report["noticeNamesTheWayOut"]
    assert report["openInTabStillPresent"]
