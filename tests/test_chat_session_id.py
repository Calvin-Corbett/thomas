"""The injected panels know which chat is open, and ask only for its rows (2026-09-05).

codex's finding: the question panel polled without a session and the book
answered with every chat's questions. One shared source now learns the open
chat's id from the request the page sends and the stream's ``done`` event,
falling back to the sidebar's current row; both panels send it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "chat_session_id.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_open_chat_is_learned_from_the_send_and_the_stream_and_the_row() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "chat_session_id.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report["nothing_known"] == ""
    assert report["row_fallback"] == "row-session"
    assert report["after_send"] == "sent-session"
    assert report["other_routes_ignored"] == "sent-session"
    assert report["after_done"] == "stream-session"
    assert report["text_events_ignored"] == "stream-session"
    # a new chat sends no session id: forget the old one and fall back to the row
    assert report["new_chat_clears"] == ""
    assert report["new_chat_uses_row"] == "row-session"
    assert report["passthrough_calls"] == 3
    assert report["before_switch"] == "stream-session"
    assert report["after_switch"] == "other-row"
    assert report["after_create"] == "fresh-session"


def test_both_panels_send_the_open_chats_id_and_skip_without_one() -> None:
    ask = (JS / "ask_user_panel.js").read_text(encoding="utf-8")
    todo = (JS / "todo_panel.js").read_text(encoding="utf-8")
    for source in (ask, todo):
        assert "ThomasChatSession" in source
        assert "session_id=" in source
    # the answer carries the chat it came from; the route refuses another chat's
    assert "session_id: sid" in ask or "session_id: session" in ask


def test_the_session_source_is_injected_before_the_panels() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    html = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert html.index("chat_session_id.js") < html.index("ask_user_panel.js")
    assert html.index("chat_session_id.js") < html.index("todo_panel.js")
