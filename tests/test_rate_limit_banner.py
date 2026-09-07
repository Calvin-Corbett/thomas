"""A resting model is announced with a countdown (frontier parity: Codex rate-limit banner, 2026-09-05).

The client parks a profile after a 429; the page saw a generic error and
nothing about when the model would be back. The banner folds the runtime
receipt (a skipped attempt with its cooldown), the error text, and the
cooldown route, and counts down.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "rate_limit_banner.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_banner_folds_receipt_error_and_route_and_counts_down() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "rate_limit_banner.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["text_ignored"] is None
    assert report["from_receipt"] == {
        "profile": "gpt-5.6-sol",
        "until": 1_200_000,
        "via": "claude-x",
        "kind": "rate_limit",
    }
    assert report["line_receipt"] == "gpt-5.6-sol is rate-limited · back in 3:15 · replies come from claude-x meanwhile"
    assert report["from_error"] == {"profile": "gpt-5.6-sol", "until": 1_045_000, "via": ""}
    assert report["line_error"] == "gpt-5.6-sol is rate-limited · back in 0:45 · Thomas will try again when it clears"
    # the route: the longest wait is the one that matters
    assert report["from_route"] == {"profile": "gpt-5.6-sol", "until": 1_090_000, "kind": "rate_limit"}
    assert report["line_route"] == "gpt-5.6-sol is rate-limited · back in 1:30 · Thomas will try again when it clears"
    assert report["line_expired"] == ""
    assert report["empty_route_clears"] is None
    assert report["format_null"] == ""
    assert report["clock"] == ["0:00", "0:59", "3:20", "1:02:05"]


def test_the_banner_is_injected_with_the_other_chat_modules() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    html = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert html.count("rate_limit_banner.js") == 1
    assert html.index("chat_session_id.js") < html.index("rate_limit_banner.js")
