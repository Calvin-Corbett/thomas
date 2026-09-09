"""Fast mode has a visible control (frontier parity: Claude Code /fast).

The V2 chat route has always honoured ``mode: "fast"`` in the request body and
``advanced.runtime.default_mode`` in preferences; until 2026-09-05 neither had
a control anywhere on the page.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "thomas" / "server" / "web" / "js" / "fast_mode.js"
DRIVER = ROOT / "tests" / "web_node" / "fast_mode.mjs"
SETTINGS_MODULE = ROOT / "thomas" / "server" / "web" / "js" / "settings_parity.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_toggle_marks_only_chat_requests_and_only_while_on() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(MODULE)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["on_adds_mode"] == "fast"
    assert report["off_leaves_body"] == '{"message":"hi"}'
    # a body that already names a mode is the page's decision, not the toggle's
    assert report["explicit_mode_kept"] == "thinking"
    assert report["non_json_untouched"] == "not json"
    assert report["chat_body_mode"] == "fast"
    assert report["chat_body_keeps_fields"] == "s1"
    assert report["chat_reply_passthrough"] == "/api/v2/chat"
    assert report["other_route_untouched"] == '{"message":"hi"}'
    assert report["get_untouched"] is True
    assert report["off_later_untouched"] is True
    assert report["call_count"] == 4


def test_the_chat_page_carries_the_toggle_once() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    once = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert once.count("fast_mode.js") == 1
    assert inject_ask_user_panel(once) == once


def test_settings_offers_the_saved_reply_speed() -> None:
    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    assert 'id="replySpeed"' in source
    assert "default_mode" in source
    for value in ("auto", "fast", "thinking"):
        assert f'value="{value}"' in source
