"""Redesign is "edit this thing however I say" (2026-09-06).

You said: "ITS NOT JUST RESIZING. ITS SENDING THOMAS A MESSAGE SAYING EDIT THIS
THING HOWEVER I SAY ... make thomas do everything ui wise through ui redesign.
this will prove he can edit himself." Pointing at the composer's "+" and asking
for a menu ended as "Nothing changed": the overlay has no channel for that, and
the client only opened a Code thread when the overlay had changed something,
with a brief that told Thomas the change was already done and the stock files
needed no edit.

Now the brief is a directive to change Thomas's own UI source, it names the
ask and everything the overlay could not do, and the client opens the thread
and sends it whenever the overlay could not carry the whole ask.
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.routes import ui_redesign_runtime as rt

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    {"uiId": "chat.composer", "label": "Add files button", "component": "button", "box": {"width": 28, "height": 28}}
]
UNSUPPORTED = [
    {
        "target_index": 0,
        "label": "Add files button",
        "reason": "a menu with new actions is not something a style or layout record can make",
    }
]


def test_the_brief_tells_thomas_to_change_his_own_source() -> None:
    brief = rt.code_thread_prompt(
        "turn this plus into a menu: create image, create video, create music, redesign with AI",
        TARGETS,
        "chat",
        unsupported=UNSUPPORTED,
        applied=[],
    )
    low = brief.lower()
    assert "turn this plus into a menu" in brief
    assert "a menu with new actions" in brief  # every reason the overlay gave
    assert "thomas/server/web" in low and "chat.html" in low  # where stock Thomas lives
    assert "web.playtest" in low or "verify" in low  # prove it in the browser
    assert "nothing in the stock ui files needs editing" not in low
    assert "only if" not in low  # no more "open this only if"


def test_the_brief_says_what_the_overlay_already_did() -> None:
    brief = rt.code_thread_prompt(
        "make it green and add a menu",
        TARGETS,
        "chat",
        unsupported=UNSUPPORTED,
        applied=["Add files button: style backgroundColor=#47d7ac"],
    )
    assert "already" in brief.lower() and "backgroundColor" in brief


def test_the_client_sends_the_thread_when_the_overlay_could_not_do_the_ask() -> None:
    js = (ROOT / "thomas" / "server" / "web" / "js" / "ui_redesign_select.js").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "needsCode" in js, "the client still opens a thread only when the overlay changed something"
    assert "async function sendThread" in js and ".send(prompt" in js, (
        "the thread is parked in the composer instead of sent"
    )
    assert "Sent to Thomas" in js
